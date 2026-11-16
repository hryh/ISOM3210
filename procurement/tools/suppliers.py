"""Supplier research tool — Stagehand-driven browsing (agent blackbox).

Two supplier shapes are supported:

- **Catalog sites** (no ``catalog_url``): one page lists every product with
  its commercial terms (the mock world). Extract once, fill shipping gaps from
  the terms page.
- **Aggregator sites** (``catalog_url`` set, e.g. price.com.hk): search for
  the request, then deep-scrape a *bounded* set of product pages for per-shop
  offers. The fence: at most ``MAX_PRODUCT_PAGES`` product pages, at most
  ``MAX_OFFERS_PER_PRODUCT`` offers each, ``MAX_RESEARCH_SECONDS`` and
  ``MAX_ACTIONS_PER_SUPPLIER`` overall. Within the fence, the deterministic
  rules engine picks the best compliant offer.

Unknown facts stay ``None`` (three-valued logic) — never zero or invented
defaults. Navigation is deterministic (DOM link clicks); the LLM only reads
pages. Research can never access portal submission.
"""

from __future__ import annotations

import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote_plus

from pydantic import BaseModel, Field

from ..catalog import BOOL, CATEGORIES, INT, LIST, OTHER_CATEGORY
from ..money import parse_hkd_minor
from ..schemas import (
    ComparisonResult,
    EligibilityResult,
    OfferEvidence,
    PurchaseRequest,
)

#: Deep-scrape fence per supplier.
MAX_PRODUCT_PAGES = 6
MAX_OFFERS_PER_PRODUCT = 5
MAX_RESEARCH_SECONDS = 120
MAX_ACTIONS_PER_SUPPLIER = 25


# ---------------------------------------------------------------------------
# Extraction schemas
# ---------------------------------------------------------------------------


class _ScrapedProduct(BaseModel):
    """One catalog row. ``None`` means "not extractable", never a default."""

    product_id: str | None = None
    model_name: str | None = None
    unit_price_hkd: str | None = None
    available_units: int | None = None
    shipping_hkd: str | None = None
    warranty_months: int | None = None
    delivery_business_days: int | None = None
    attributes: dict[str, Any] | None = None
    unknown_fields: dict[str, str] = Field(default_factory=dict)


class _CatalogPage(BaseModel):
    products: list[_ScrapedProduct] = Field(default_factory=list)


class _ListingProduct(BaseModel):
    product_name: str
    price_hkd: str | None = None
    description: str | None = None


class _ListingPage(BaseModel):
    products: list[_ListingProduct] = Field(default_factory=list)


class _ShopOffer(BaseModel):
    shop_name: str | None = None
    price_hkd: str | None = None
    warranty_text: str | None = None
    stock_text: str | None = None
    #: Availability classified by the extractor into a fixed vocabulary; the
    #: rules engine consumes the label, the raw text is kept for humans.
    stock_state: str | None = None


class _ProductDetails(BaseModel):
    specifications: str | None = None
    #: Typed category attributes extracted from the spec text, normalized to
    #: the catalog's canonical values ("FHD"/"1920X1080" -> "1920x1080").
    attributes: dict[str, Any] | None = None
    offers: list[_ShopOffer] = Field(default_factory=list)


class _ShippingTerms(BaseModel):
    standard_shipping_fee_hkd: str | None = None
    delivery_business_days: int | None = None


# ---------------------------------------------------------------------------
# Small deterministic helpers
# ---------------------------------------------------------------------------


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug[:60] or "item"


def _search_phrase(request: PurchaseRequest) -> str:
    """The natural-language phrase used to search an aggregator site.

    For free-text requests the required keywords join the item description so
    brand/model terms ("Thinkpad") actually reach the site's search box —
    otherwise the query is just the generic item ("laptop") and the keyword
    can only ever reject offers, never find them.
    """
    req = request.mandatory
    if req.category == OTHER_CATEGORY:
        parts = [str(req.attributes.get("item") or "").strip()]
        parts.extend(
            str(k).strip()
            for k in (req.attributes.get("keywords") or [])
            if str(k).strip()
        )
        return " ".join(p for p in parts if p)
    spec = CATEGORIES.get(req.category)
    parts = [spec.label] if spec else [req.category]
    for key, value in (req.attributes or {}).items():
        if isinstance(value, (list, tuple)):
            parts.extend(str(v) for v in value)
        elif value is not None:
            parts.append(str(value))
    return " ".join(parts)


def _request_keywords(request: PurchaseRequest) -> list[str]:
    """Deterministic keywords used to rank search results."""
    req = request.mandatory
    keywords: list[str] = []
    if req.category == OTHER_CATEGORY:
        keywords = [str(k) for k in (req.attributes.get("keywords") or [])]
    else:
        for value in (req.attributes or {}).values():
            if isinstance(value, (list, tuple)):
                keywords.extend(str(v) for v in value)
            elif value is not None:
                keywords.append(str(value))
    return [k.strip().lower() for k in keywords if k and k.strip()]


def _rank_listing(
    products: list[_ListingProduct], request: PurchaseRequest
) -> list[_ListingProduct]:
    """Deterministic ranking: keyword matches first, then lowest price."""
    keywords = _request_keywords(request)

    def score(item: _ListingProduct) -> tuple[int, int]:
        text = f"{item.product_name} {item.description or ''}".lower()
        matches = sum(1 for k in keywords if k in text)
        price = parse_hkd_minor(item.price_hkd)
        return (-matches, price if price is not None else 10**12)

    ranked = sorted(products, key=score)
    if keywords:
        matching = [
            p for p in ranked if any(k in f"{p.product_name} {p.description or ''}".lower() for k in keywords)
        ]
        if matching:
            return matching
    return ranked


def _extract_months(text: str | None) -> int | None:
    """Parse an explicit warranty duration; never invent a default."""
    if not text:
        return None
    match = re.search(r"(\d+)\s*(個月|个月|months?|mo\b)", text, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _extract_stock_count(text: str | None) -> int | None:
    """Parse an explicit stock count, e.g. '3件' or '5 units'."""
    if not text:
        return None
    match = re.search(r"(\d+)\s*(件|部|個|units?\b|pcs)", text, re.IGNORECASE)
    return int(match.group(1)) if match else None


# ---------------------------------------------------------------------------
# Catalog-page flow (mock world)
# ---------------------------------------------------------------------------


def _catalog_instruction(request: PurchaseRequest, supplier_name: str) -> str:
    req = request.mandatory
    if req.category == OTHER_CATEGORY:
        item = req.attributes.get("item", "")
        return (
            f"Extract every product listed on this {supplier_name} catalogue "
            f"page that matches: {item}. For each product return: product_id "
            "(from the product link URL if visible), model_name, "
            "unit_price_hkd (the unit price exactly as shown), available_units "
            "(units in stock), shipping_hkd (the shipping fee; set to null if "
            "not shown), warranty_months (warranty in months, null if not "
            "specified), delivery_business_days (delivery time in business "
            "days, null if not specified), and attributes as an object with "
            "'specifications' (the full specifications text shown for the "
            "product, translated into English if shown in another language) "
            "and 'stock_status' (the stock/availability text, null if not "
            "shown). If nothing matches or this is not a catalogue "
            "page, return an empty list."
        )
    spec = CATEGORIES.get(req.category)
    attr_names = [a.display_name for a in spec.attributes] if spec else []
    attr_hint = ", ".join(attr_names) if attr_names else "the listed specifications"
    label = spec.label if spec else req.category
    return (
        f"Extract every {label} product listed on this {supplier_name} catalogue "
        "page. For each product return: product_id (from the product link URL if "
        "visible), model_name, unit_price_hkd (the unit price exactly as shown), "
        "available_units (units in stock), shipping_hkd (the shipping fee; set to "
        "null if the page says to see the terms page or does not show one), "
        "warranty_months (warranty in months, null if not specified), "
        "delivery_business_days (delivery time in business days, null if not "
        f"specified), and attributes (an object with: {attr_hint}; use null for "
        "anything not stated). Only include products that are "
        f"{label.lower()}s. If the catalogue is empty or not a catalogue page, "
        "return an empty list."
    )


def _coerce_attributes(category: str, raw: dict[str, Any] | None) -> dict[str, Any]:
    """Map extracted attributes back onto the catalog's typed keys.

    The extraction prompt uses display names ("screen size (inches)"), but the
    rules engine compares by catalog key and type. Strings are coerced: int
    attrs to int, bool attrs to Yes/No booleans, list attrs to lists.
    Free-text ("other") requests keep the extracted attributes verbatim.
    """
    spec = CATEGORIES.get(category)
    raw = raw or {}
    out: dict[str, Any] = {}
    if spec is None:
        # Free-text category: keep exactly what the browser showed.
        return {k: v for k, v in raw.items() if v is not None}
    display_to_name = {a.display_name: a.name for a in spec.attributes}
    for attr in spec.attributes:
        value = raw.get(attr.name, raw.get(attr.display_name))
        if value is None or value == "":
            continue
        if attr.type == INT:
            try:
                out[attr.name] = int(str(value).strip())
            except (TypeError, ValueError):
                continue
        elif attr.type == BOOL:
            if isinstance(value, bool):
                out[attr.name] = value
            else:
                out[attr.name] = str(value).strip().lower() in ("yes", "true", "y")
        elif attr.type == LIST:
            if isinstance(value, (list, tuple)):
                out[attr.name] = [str(v).strip() for v in value]
            elif isinstance(value, str):
                out[attr.name] = [v.strip() for v in value.split(",") if v.strip()]
            else:
                out[attr.name] = [str(value)]
        else:
            out[attr.name] = str(value).strip()
    return out


def _to_evidence(
    scraped: _ScrapedProduct,
    *,
    supplier_id: str,
    category: str,
    shipping_minor_fallback: int | None,
    retrieved_at,
) -> OfferEvidence | None:
    """Convert a scraped row into an OfferEvidence, keeping unknowns unknown."""
    if scraped.model_name is None and scraped.product_id is None:
        return None

    product_key = scraped.product_id or (scraped.model_name or "product").strip()

    unit_price_minor = parse_hkd_minor(scraped.unit_price_hkd)
    shipping_minor = parse_hkd_minor(scraped.shipping_hkd)
    if shipping_minor is None:
        shipping_minor = shipping_minor_fallback

    unknown_fields: dict[str, str] = dict(scraped.unknown_fields)
    if unit_price_minor is None:
        unknown_fields["unit_price_minor"] = "price not extractable from the catalog"
    if shipping_minor is None:
        unknown_fields["shipping_minor"] = "shipping not shown on the catalog"

    delivery_by: date | None = None
    if scraped.delivery_business_days is not None:
        delivery_by = retrieved_at.date() + timedelta(
            days=int(scraped.delivery_business_days)
        )

    return OfferEvidence(
        offer_id=f"{supplier_id}:{product_key}",
        supplier_id=supplier_id,
        product_id=product_key,
        category=category,
        model_name=scraped.model_name,
        unit_price_minor=unit_price_minor,
        available_quantity=scraped.available_units,
        shipping_minor=shipping_minor,
        attributes=_coerce_attributes(category, scraped.attributes),
        warranty_months=scraped.warranty_months,
        delivery_by=delivery_by,
        retrieved_at=retrieved_at,
        unknown_fields=unknown_fields,
    )


async def _research_catalog_page(browser, request: PurchaseRequest, supplier) -> list[OfferEvidence]:
    """Mock-world flow: one catalog page carries every product and term."""
    category = request.mandatory.category
    retrieved_at = datetime.now(timezone.utc)
    actions = 0

    await browser.goto(supplier.origin)
    actions += 1

    # Reach a catalogue that lists products: deterministic DOM click first,
    # LLM act as fallback for live layouts.
    if not await browser.click_link_containing(supplier.name):
        try:
            await browser.act(
                f"click the link that leads to the catalogue or shop page for "
                f"{supplier.name}"
            )
            actions += 1
        except Exception:
            pass  # already on a catalogue-like page

    try:
        page = await browser.extract(
            _catalog_instruction(request, supplier.name), _CatalogPage
        )
    except Exception:
        return []

    scraped_rows = page.products if page else []

    shipping_minor_fallback: int | None = None
    needs_terms = any(
        s.shipping_hkd is None or parse_hkd_minor(s.shipping_hkd or "") is None
        for s in scraped_rows
        if category != OTHER_CATEGORY
    )
    if scraped_rows and needs_terms and actions < MAX_ACTIONS_PER_SUPPLIER:
        try:
            await browser.act("open the shipping, delivery and returns terms page")
            terms = await browser.extract(
                "extract the standard shipping fee and the delivery time in "
                "business days from this terms page",
                _ShippingTerms,
            )
            shipping_minor_fallback = parse_hkd_minor(terms.standard_shipping_fee_hkd)
        except Exception:
            shipping_minor_fallback = None

    return [
        evidence
        for s in scraped_rows
        if (
            evidence := _to_evidence(
                s,
                supplier_id=str(supplier.id),
                category=category,
                shipping_minor_fallback=shipping_minor_fallback,
                retrieved_at=retrieved_at,
            )
        )
        is not None
    ]


# ---------------------------------------------------------------------------
# Aggregator deep-scrape flow (price.com.hk style)
# ---------------------------------------------------------------------------


def _listing_instruction(phrase: str) -> str:
    return (
        f"These are shopping search results for '{phrase}'. List up to 15 "
        "products that are relevant to that search. For each product return: "
        "product_name (the exact product title shown), price_hkd (the lowest "
        "price displayed for it, exactly as shown), and description (the "
        "specifications or summary text shown in the result row). Ignore ads, "
        "banner deals and unrelated categories."
    )


def _typed_attribute_hints(category: str) -> str:
    """Extraction guidance per catalog attribute, with normalization rules.

    Only typed categories use this; "other" keeps the free specifications
    text. Values are normalized to the catalog's canonical choices so the
    deterministic rules engine can compare them exactly.
    """
    spec = CATEGORIES.get(category)
    if spec is None:
        return ""
    lines = []
    for attr in spec.attributes:
        if attr.type == INT:
            lines.append(
                f"- '{attr.display_name}': the number as an integer "
                f"(e.g. 27); null if not stated"
            )
        elif attr.type == BOOL:
            lines.append(
                f"- '{attr.display_name}': true or false; null if not stated"
            )
        elif attr.type == LIST:
            lines.append(
                f"- '{attr.display_name}': a list of the values that appear, "
                f"chosen from {list(attr.choices)} (e.g. 'HDMI x1, DP' -> "
                "[\"HDMI\", \"DisplayPort\"]); null if not stated"
            )
        elif attr.choices:
            lines.append(
                f"- '{attr.display_name}': normalize to exactly one of "
                f"{list(attr.choices)} (e.g. FHD/1080p/1920X1080 -> "
                "\"1920x1080\"); null if not stated"
            )
        else:
            lines.append(f"- '{attr.display_name}': the stated value; null if not stated")
    return "\n".join(lines)


def _product_instruction(product_name: str, request: PurchaseRequest) -> str:
    category = request.mandatory.category
    typed_hints = _typed_attribute_hints(category)
    attributes_part = ""
    if typed_hints:
        attributes_part = (
            "First, 'attributes': an object describing THIS product, "
            "reading its specification text, with these keys (normalize "
            "variants to the canonical values; never guess a value the page "
            "does not state):\n"
            f"{typed_hints}\n"
        )
    return (
        f"This is a price-comparison page for: {product_name}. Extract "
        + ("three" if typed_hints else "two")
        + " things. "
        + attributes_part
        + "Next, 'specifications': the product's specification text "
        "shown on this page as one string — TRANSLATE it into English if it is "
        "in another language (keep model names, brands and numbers exactly as "
        "shown; translate feature terms like 降噪 to 'noise cancelling'). "
        "Finally, 'offers': a list of up to "
        f"{MAX_OFFERS_PER_PRODUCT} seller offers shown on this page, each with "
        "shop_name (the seller/shop name), price_hkd (the offer price exactly "
        "as shown), warranty_text (warranty or goods-type info, e.g. 行貨/水貨, "
        "null if not shown), stock_text (the stock/availability text exactly as "
        "shown, null if not shown), and stock_state: classify the availability "
        "as exactly one of 'in_stock', 'low_stock', 'out_of_stock', 'preorder' "
        "(orderable, arrives in days) or null when the page shows no "
        "availability information. Do not include offers without a price."
    )


def _shop_offer_to_evidence(
    offer: _ShopOffer,
    details: _ProductDetails,
    listing: _ListingProduct,
    request: PurchaseRequest,
    supplier,
    retrieved_at,
) -> OfferEvidence | None:
    unit_price_minor = parse_hkd_minor(offer.price_hkd)
    if unit_price_minor is None:
        return None

    category = request.mandatory.category
    shop = (offer.shop_name or "shop").strip()
    product_key = f"{_slug(listing.product_name)}--{_slug(shop)}"

    specifications = " ".join(
        part
        for part in (details.specifications, listing.description, listing.product_name)
        if part
    )
    attributes: dict[str, Any] = {}
    # Typed specs from the product page, coerced to the catalog's keys so the
    # deterministic rules can compare them (unknowns simply stay absent).
    attributes.update(_coerce_attributes(category, details.attributes))
    # Human-readable context and availability, always kept.
    attributes["shop"] = shop
    attributes["specifications"] = specifications
    if offer.stock_text:
        attributes["stock_status"] = offer.stock_text
    if offer.stock_state:
        attributes["stock_state"] = offer.stock_state

    unknown_fields: dict[str, str] = {}
    if offer.stock_text is None:
        unknown_fields["stock_status"] = "no availability text on the offer"
    unknown_fields["shipping_minor"] = "aggregator offers do not list shipping"

    return OfferEvidence(
        offer_id=f"{supplier.id}:{product_key}",
        supplier_id=str(supplier.id),
        product_id=product_key,
        category=category,
        model_name=listing.product_name[:120],
        unit_price_minor=unit_price_minor,
        available_quantity=_extract_stock_count(offer.stock_text),
        shipping_minor=None,
        attributes=attributes,
        warranty_months=_extract_months(offer.warranty_text),
        delivery_by=None,
        retrieved_at=retrieved_at,
        unknown_fields=unknown_fields,
    )


async def _research_aggregator(browser, request: PurchaseRequest, supplier, started: float) -> list[OfferEvidence]:
    """Bounded deep scrape: search → top product pages → per-shop offers."""
    retrieved_at = datetime.now(timezone.utc)
    phrase = _search_phrase(request)
    if not phrase:
        return []

    entry = supplier.catalog_url or supplier.origin
    if "{query}" in entry:
        url = entry.replace("{query}", quote_plus(phrase))
    else:
        url = entry

    await browser.goto(url)
    await browser.wait_until_ready()
    await browser.settle(3.0)

    listing = None
    for _attempt in range(4):
        try:
            listing = await browser.extract(_listing_instruction(phrase), _ListingPage)
            if listing and listing.products:
                break
        except Exception:
            # Bot-protection remnants (vanishing iframes) can break the
            # accessibility snapshot mid-read — settle and retry.
            listing = None
        await browser.settle(6.0)
    candidates = _rank_listing(listing.products if listing else [], request)

    evidences: list[OfferEvidence] = []
    actions = 0
    for index, item in enumerate(candidates[:MAX_PRODUCT_PAGES]):
        if (
            time.monotonic() - started > MAX_RESEARCH_SECONDS
            or actions >= MAX_ACTIONS_PER_SUPPLIER
        ):
            break
        # Re-load the search page for each product: SPA-style product links
        # break history navigation, so "back" cannot be relied on.
        if index > 0:
            await browser.goto(url)
            await browser.wait_until_ready(10)
            await browser.settle(2.0)
        # Open the product page by its title: cheap DOM click first, then
        # observe-based resolution for layouts the DOM click cannot handle.
        if not await browser.click_link_to(item.product_name[:60]):
            continue
        actions += 1
        details: _ProductDetails | None = None
        try:
            details = await browser.extract(
                _product_instruction(item.product_name, request), _ProductDetails
            )
        except Exception:
            details = None
        if details is not None:
            for offer in details.offers[:MAX_OFFERS_PER_PRODUCT]:
                evidence = _shop_offer_to_evidence(
                    offer, details, item, request, supplier, retrieved_at
                )
                if evidence is not None:
                    evidences.append(evidence)
        # (No go_back: the loop reloads the search page instead — see above.)
        actions += 1

    return evidences


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def _headless_for(supplier) -> bool:
    """Headless for mock/catalog sites; visible browser for aggregator sites.

    Live aggregator sites (e.g. price.com.hk) sit behind bot protection that
    a headless browser fails; a visible Chrome window passes the check — and
    makes the demo watchable. ``STAGEHAND_HEADLESS`` overrides both.
    """
    env = os.getenv("STAGEHAND_HEADLESS")
    if env is not None:
        return env.lower() not in ("false", "0", "no")
    return not bool(supplier.catalog_url)


async def research_supplier(request: PurchaseRequest, supplier) -> list[OfferEvidence]:
    """Browse one supplier's site and extract product evidence.

    ``supplier`` is a ``procurement.repository.Supplier`` row. Suppliers with a
    ``catalog_url`` use the bounded aggregator deep-scrape flow; the rest use
    the single catalog-page flow.
    """
    from .browser import StagehandBrowser

    browser = StagehandBrowser(headless=_headless_for(supplier))
    started = time.monotonic()
    await browser.start()
    try:
        if supplier.catalog_url:
            return await _research_aggregator(browser, request, supplier, started)
        return await _research_catalog_page(browser, request, supplier)
    finally:
        await browser.close()


def validate_offer(request: PurchaseRequest, offer: OfferEvidence) -> EligibilityResult:
    """Delegate to the deterministic rules engine (already implemented)."""
    from ..rules import validate_offer as _validate

    return _validate(request, offer)


def compare_offers(
    request: PurchaseRequest,
    offers: list[OfferEvidence],
    results: list[EligibilityResult],
) -> ComparisonResult:
    """Delegate to the deterministic rules engine (already implemented)."""
    from ..rules import compare_offers as _compare

    return _compare(request, offers, results)
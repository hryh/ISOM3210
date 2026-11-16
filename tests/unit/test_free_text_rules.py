"""Free-text ("other") category: rules, parsing, and research helpers."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from procurement.catalog import OTHER_CATEGORY
from procurement.money import parse_hkd_minor
from procurement.parsing import ClarificationNeeded, draft_to_request
from procurement.rules import (
    compare_offers,
    validate_offer,
)
from procurement.schemas import OfferEvidence, RequestDraft, ValidationStatus
from tests.conftest import MONITOR_ATTRIBUTES  # noqa: F401 - fixture module


def _other_request(make_request, keywords: list[str], **overrides):
    return make_request(
        category=OTHER_CATEGORY,
        attributes={"item": "noise cancelling headphones", "keywords": keywords},
        **overrides,
    )


def _offer(**kwargs) -> OfferEvidence:
    defaults = dict(
        offer_id="SUP1:item--shop",
        supplier_id="SUP1",
        product_id="item--shop",
        category=OTHER_CATEGORY,
        model_name="Sony WH-1000XM5",
        unit_price_minor=1_500,
        shipping_minor=None,
        available_quantity=None,
        attributes={
            "shop": "Tech Store",
            "specifications": "Sony WH-1000XM5 wireless noise cancelling headphones",
        },
        warranty_months=None,
        delivery_by=None,
    )
    defaults.update(kwargs)
    from datetime import datetime, timezone

    defaults.setdefault("retrieved_at", datetime.now(timezone.utc))
    return OfferEvidence(**defaults)


# --- rules: keyword validation -------------------------------------------------


def test_keyword_present_passes(make_request):
    request = _other_request(make_request, ["noise cancelling", "wireless"])
    offer = _offer(
        attributes={"specifications": "Wireless over-ear headphones with noise cancelling, bluetooth"}
    )
    result = validate_offer(request, offer)
    keyword_checks = [c for c in result.checks if c.field in ("noise cancelling", "wireless")]
    assert all(c.status is ValidationStatus.PASS for c in keyword_checks)


def test_keyword_missing_fails(make_request):
    request = _other_request(make_request, ["noise cancelling", "usb transmitter"])
    offer = _offer()
    result = validate_offer(request, offer)
    check = next(c for c in result.checks if c.field == "usb transmitter")
    assert check.status is ValidationStatus.FAIL


def test_typed_categories_still_validate(make_request, make_offer):
    request = make_request()  # monitor with typed attributes
    result = validate_offer(request, make_offer())
    assert result.status is ValidationStatus.PASS


# --- rules: textual stock evidence --------------------------------------------


def test_stock_state_labels_pass(make_request):
    """The extractor's availability classification feeds rule 3."""
    request = _other_request(make_request, ["noise cancelling"], quantity=1)
    for state, expected in (
        ("in_stock", ValidationStatus.PASS),
        ("low_stock", ValidationStatus.PASS),
        ("preorder", ValidationStatus.PASS),
        ("out_of_stock", ValidationStatus.FAIL),
        (None, ValidationStatus.UNKNOWN),
    ):
        attrs = {"specifications": "noise cancelling headphones"}
        if state:
            attrs["stock_state"] = state
        result = validate_offer(request, _offer(attributes=attrs))
        check = next(c for c in result.checks if c.field == "available_quantity")
        assert check.status is expected, (state, check.reason)


def test_in_stock_text_passes_quantity(make_request):
    request = _other_request(make_request, ["noise cancelling"], quantity=2)
    for status in ("現貨 In stock", "有存貨"):
        offer = _offer(
            attributes={"specifications": "noise cancelling", "stock_status": status}
        )
        result = validate_offer(request, offer)
        check = next(c for c in result.checks if c.field == "available_quantity")
        assert check.status is ValidationStatus.PASS
        assert "count not shown" in check.reason


def test_while_stocks_last_is_not_out_of_stock(make_request):
    """'售完即止' (while stocks last) must not read as out of stock."""
    request = _other_request(make_request, ["noise cancelling"], quantity=2)
    offer = _offer(
        attributes={
            "specifications": "noise cancelling",
            "stock_status": "限時優惠 – 售完即止",
        }
    )
    result = validate_offer(request, offer)
    check = next(c for c in result.checks if c.field == "available_quantity")
    assert check.status is ValidationStatus.UNKNOWN  # neither in nor out of stock


def test_out_of_stock_text_fails_quantity(make_request):
    request = _other_request(make_request, ["noise cancelling"], quantity=2)
    offer = _offer(
        attributes={"specifications": "noise cancelling", "stock_status": "缺貨 out of stock"}
    )
    result = validate_offer(request, offer)
    check = next(c for c in result.checks if c.field == "available_quantity")
    assert check.status is ValidationStatus.FAIL


def test_no_stock_evidence_is_unknown(make_request):
    request = _other_request(make_request, ["noise cancelling"], quantity=2)
    offer = _offer(attributes={"specifications": "noise cancelling"})
    result = validate_offer(request, offer)
    assert result.status is ValidationStatus.UNKNOWN


def test_numeric_stock_still_works(make_request):
    request = _other_request(make_request, ["noise cancelling"], quantity=2)
    offer = _offer(available_quantity=1, attributes={"specifications": "noise cancelling"})
    result = validate_offer(request, offer)
    check = next(c for c in result.checks if c.field == "available_quantity")
    assert check.status is ValidationStatus.FAIL


# --- rules: shipping-unknown budget caveat ------------------------------------


def test_unknown_shipping_budgets_without_shipping(make_request):
    request = _other_request(
        make_request, ["noise cancelling"], quantity=2, max_total_minor=5_000
    )
    offer = _offer(
        unit_price_minor=2_000,
        available_quantity=10,
        attributes={"specifications": "noise cancelling", "stock_status": "in stock"},
    )
    result = validate_offer(request, offer)
    check = next(c for c in result.checks if c.field == "verified_total")
    assert check.status is ValidationStatus.PASS
    assert "shipping unverified" in check.reason
    assert result.verified_total_minor == 4_000


def test_unknown_shipping_over_budget_fails(make_request):
    request = _other_request(
        make_request, ["noise cancelling"], quantity=2, max_total_minor=1_000
    )
    offer = _offer(
        unit_price_minor=2_000,
        available_quantity=10,
        attributes={"specifications": "noise cancelling", "stock_status": "in stock"},
    )
    result = validate_offer(request, offer)
    assert result.status is ValidationStatus.FAIL


def test_known_shipping_still_verified_exactly(make_request, make_offer):
    request = make_request()
    result = validate_offer(request, make_offer(shipping_minor=15_000))
    check = next(c for c in result.checks if c.field == "verified_total")
    assert check.status is ValidationStatus.PASS
    assert "shipping" not in check.reason


# --- parsing: "other" drafts ----------------------------------------------------


def _other_draft(**overrides) -> RequestDraft:
    defaults = dict(
        category=OTHER_CATEGORY,
        quantity=1,
        attributes={"item": "standing desk", "keywords": ["electric", "160cm"]},
        warranty_months_min=None,
        max_total_hkd="5000",
        deadline="2026-12-01",
        department="engineering",
    )
    defaults.update(overrides)
    return RequestDraft(**defaults)


def test_draft_other_becomes_request():
    request = draft_to_request(_other_draft(), request_id="R", requester="u")
    assert request.mandatory.category == OTHER_CATEGORY
    assert request.mandatory.attributes["item"] == "standing desk"
    assert request.mandatory.attributes["keywords"] == ["electric", "160cm"]


def test_draft_other_requires_item():
    with pytest.raises(ClarificationNeeded):
        draft_to_request(_other_draft(attributes={"keywords": ["x"]}), request_id="R", requester="u")


def test_draft_other_requires_keywords():
    with pytest.raises(ClarificationNeeded):
        draft_to_request(_other_draft(attributes={"item": "desk"}), request_id="R", requester="u")


def test_unknown_category_still_rejected():
    with pytest.raises(ClarificationNeeded):
        draft_to_request(_other_draft(category="spaceship"), request_id="R", requester="u")


# --- research helpers (pure) ----------------------------------------------------


def test_search_phrase_other():
    from procurement.tools.suppliers import _search_phrase

    request = _make_request_helper(
        category=OTHER_CATEGORY,
        attributes={"item": "noise cancelling headphones", "keywords": ["x"]},
    )
    assert _search_phrase(request) == "noise cancelling headphones"


def _make_request_helper(
    quantity: int = 1,
    max_total_minor: int = 1_000_000,
    category: str = OTHER_CATEGORY,
    attributes: dict | None = None,
    warranty_months_min: int | None = None,
):
    from datetime import date

    from procurement.schemas import PurchaseRequest, RequestRequirements

    return PurchaseRequest(
        request_id="R",
        requester="t",
        department="d",
        category=category,
        quantity=quantity,
        max_total_cost_minor=max_total_minor,
        deadline=date(2026, 12, 1),
        mandatory=RequestRequirements(
            category=category, attributes=attributes or {}, warranty_months_min=warranty_months_min
        ),
        created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )


def test_search_phrase_typed():
    from procurement.tools.suppliers import _search_phrase

    request = _make_request_helper(
        category="monitor",
        attributes=MONITOR_ATTRIBUTES,
    )
    phrase = _search_phrase(request)
    assert "Monitor" in phrase
    assert "27" in phrase
    assert "2560x1440" in phrase


def test_rank_listing_prefers_keyword_matches_and_price():
    from procurement.tools.suppliers import _ListingProduct, _rank_listing

    request = _other_request(_make_request_helper, ["noise cancelling"])
    products = [
        _ListingProduct(product_name="Cheap Earbuds", price_hkd="HK$100", description=""),
        _ListingProduct(product_name="Sony WH-1000XM4", price_hkd="HK$2,899", description="noise cancelling"),
        _ListingProduct(product_name="Bose QC45", price_hkd="HK$1,999", description="noise cancelling"),
        _ListingProduct(product_name="Studio Mic", price_hkd="HK$800", description=""),
    ]
    ranked = _rank_listing(products, request)
    assert ranked[0].product_name == "Bose QC45"
    assert ranked[1].product_name == "Sony WH-1000XM4"
    assert "Studio Mic" not in [p.product_name for p in ranked]


def test_extract_months_english_and_chinese():
    from procurement.tools.suppliers import _extract_months

    assert _extract_months("12 months warranty") == 12
    assert _extract_months("保養36個月") == 36
    assert _extract_months("行貨") is None
    assert _extract_months(None) is None


def test_extract_stock_count():
    from procurement.tools.suppliers import _extract_stock_count

    assert _extract_stock_count("3件") == 3
    assert _extract_stock_count("5 units") == 5
    assert _extract_stock_count("in stock") is None
    assert _extract_stock_count(None) is None


def test_shop_offer_evidence_shape():
    from datetime import datetime, timezone

    from procurement.tools.suppliers import (
        _ListingProduct,
        _ProductDetails,
        _ShopOffer,
        _shop_offer_to_evidence,
    )

    class _Sup:
        id = 7

    offer = _ShopOffer(shop_name="Star Tech", price_hkd="HK$1,480", warranty_text="12個月保養", stock_text="現貨")
    details = _ProductDetails(specifications="Sony WH-1000XM5 noise cancelling headphones")
    listing = _ListingProduct(product_name="Sony WH-1000XM5", price_hkd="HK$1,480", description="")
    request = _other_request(_make_request_helper, ["noise cancelling"])

    evidence = _shop_offer_to_evidence(
        offer, details, listing, request, _Sup(), datetime.now(timezone.utc)
    )
    assert evidence.unit_price_minor == 148_000
    assert evidence.warranty_months == 12
    assert evidence.available_quantity is None
    assert evidence.attributes["shop"] == "Star Tech"
    assert evidence.attributes["stock_status"] == "現貨"
    assert evidence.product_key if hasattr(evidence, "product_key") else True
    assert "sony-wh-1000xm5" in evidence.product_id
    assert "--star-tech" in evidence.product_id
    assert evidence.offer_id == "7:sony-wh-1000xm5--star-tech"
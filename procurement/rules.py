"""Business rules (§5 of the project proposal).

Pure functions only — no I/O, no LLM, no database. Everything here is unit
testable. All money is integer HKD minor units.

Three-valued validation: each requirement returns PASS, FAIL, or UNKNOWN.
UNKNOWN means "not enough evidence to decide", never silently converted to a
pass or a fail.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from datetime import date

from .catalog import BOOL, CATEGORIES, INT, LIST, OTHER_CATEGORY, STR, AttributeSpec
from .money import verified_total
from .schemas import (
    ApprovalRole,
    ComparisonResult,
    EligibilityResult,
    FieldValidation,
    OfferEvidence,
    PurchaseRequest,
    RequestRequirements,
    ValidationStatus,
)

#: Number of comparable quotations required before the shortfall is waived (rule 7).
QUOTATION_TARGET = 3

#: Purchases at or above this total require a manager role (rule 6). HK$10,000.
MANAGER_THRESHOLD_MINOR = 10_000 * 100


def supplier_allowed(supplier_id: str, allowlist: Iterable[str]) -> bool:
    """Rule 1: only allowlisted suppliers may be recommended."""
    return supplier_id in set(allowlist)


def required_approval_role(total_minor: int) -> ApprovalRole:
    """Rule 6: total at/above threshold requires a manager, else a requester."""
    if total_minor >= MANAGER_THRESHOLD_MINOR:
        return ApprovalRole.MANAGER
    return ApprovalRole.REQUESTER


def resolved_total_minor(offer: OfferEvidence, quantity: int) -> int | None:
    """Return the complete verified total, or ``None`` if any term is unknown.

    Rule 4/5: a total with any unresolved charge must not be treated as valid.
    """
    if offer.unit_price_minor is None or offer.shipping_minor is None:
        return None
    return verified_total(offer.unit_price_minor, quantity, offer.shipping_minor)


def _keyword_checks(req: RequestRequirements, offer: OfferEvidence) -> list[FieldValidation]:
    """Free-text category validation: every requested keyword must appear in
    the offer's extracted specifications text (or its model name).

    Deterministic substring matching — the LLM only extracted the text; Python
    decides eligibility. Matching is normalized (case, hyphens, punctuation)
    so "noise cancelling" matches "Noise-Cancelling". A keyword nobody stated
    is UNKNOWN, never assumed.
    """
    def normalize(text: str) -> str:
        return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", text.lower()).strip()

    spec_text = normalize(
        " ".join(
            str(v)
            for v in (offer.model_name, offer.attributes.get("specifications"), " ")
            if v
        )
    )
    checks: list[FieldValidation] = []
    keywords = req.attributes.get("keywords") or []
    for keyword in keywords:
        if not isinstance(keyword, str) or not keyword.strip():
            continue
        if normalize(keyword) in spec_text:
            checks.append(
                _check(keyword.strip(), ValidationStatus.PASS, "appears in the product specifications")
            )
        else:
            checks.append(
                _check(keyword.strip(), ValidationStatus.FAIL, "not found in the extracted specifications")
            )
    if not checks:
        checks.append(
            _check("item keywords", ValidationStatus.UNKNOWN, "no required keywords were extracted")
        )
    return checks


#: Textual stock evidence (aggregator sites) counts as availability, with the
#: count left unverified. Only these explicit in-stock phrases qualify.
#: Out-of-stock is checked FIRST so "無存貨" is never mistaken for stock.
_IN_STOCK_PATTERNS = ("有貨", "有存貨", "現貨", "in stock", "available")
_OUT_OF_STOCK_PATTERNS = ("缺貨", "無存貨", "售罄", "已售完", "out of stock", "sold out")


def _quantity_check(
    request: PurchaseRequest, offer: OfferEvidence
) -> FieldValidation:
    """Rule 3: a supplier must cover the entire quantity.

    A numeric stock count at/above the quantity is full evidence. Aggregator
    offers rarely show counts, so availability comes from the extractor's
    classification ('in_stock' / 'low_stock' / 'preorder' pass with the count
    left unverified; 'out_of_stock' fails) or — failing that — explicit
    in-stock phrases in the raw text. Everything else is UNKNOWN. The raw
    availability text is always kept for the human approver.
    """
    if offer.available_quantity is None:
        state = str(offer.attributes.get("stock_state") or "").lower()
        if state in ("in_stock", "low_stock"):
            note = "low stock" if state == "low_stock" else "in stock"
            return _check(
                "available_quantity",
                ValidationStatus.PASS,
                f"listed as {note} (count not shown)",
            )
        if state == "preorder":
            return _check(
                "available_quantity",
                ValidationStatus.PASS,
                "orderable, ships in a few days (count not shown)",
            )
        if state == "out_of_stock":
            return _check("available_quantity", ValidationStatus.FAIL, "listed as out of stock")
        # Fall back to the raw availability text.
        stock_status = str(offer.attributes.get("stock_status") or "").lower()
        if any(p in stock_status for p in _OUT_OF_STOCK_PATTERNS):
            return _check("available_quantity", ValidationStatus.FAIL, "listed as out of stock")
        if any(p in stock_status for p in _IN_STOCK_PATTERNS):
            return _check(
                "available_quantity",
                ValidationStatus.PASS,
                "listed as in stock (count not shown)",
            )
        return _check("available_quantity", ValidationStatus.UNKNOWN, "available quantity not extracted")
    if offer.available_quantity < request.quantity:
        return _check("available_quantity", ValidationStatus.FAIL, "insufficient stock for full quantity")
    return _check("available_quantity", ValidationStatus.PASS, "sufficient stock for full quantity")


def _check(
    field: str,
    status: ValidationStatus,
    reason: str,
    evidence_ids: Sequence[str] = (),
) -> FieldValidation:
    return FieldValidation(
        field=field, status=status, reason=reason, evidence_ids=list(evidence_ids)
    )


def _attribute_check(
    spec: AttributeSpec,
    req_value: object,
    offer_value: object,
) -> FieldValidation:
    """Three-valued check of one category attribute against the request.

    ``offer_value`` missing -> UNKNOWN (never FAIL). Otherwise compare by the
    attribute's declared type.
    """
    name = spec.name
    if offer_value is None:
        return _check(name, ValidationStatus.UNKNOWN, f"{name} not extracted")

    if spec.type == INT:
        ok = offer_value >= req_value
        reason = "meets minimum" if ok else "below minimum"
    elif spec.type == STR:
        ok = offer_value == req_value
        reason = "matches requirement" if ok else "does not match requirement"
    elif spec.type == BOOL:
        ok = bool(offer_value) == bool(req_value)
        reason = "matches requirement" if ok else "does not match requirement"
    elif spec.type == LIST:
        required = req_value if isinstance(req_value, list) else [req_value]
        missing = [c for c in required if c not in offer_value]
        ok = not missing
        reason = "all required values present" if ok else f"missing: {', '.join(missing)}"
    else:  # pragma: no cover - defensive
        return _check(name, ValidationStatus.UNKNOWN, f"unknown attribute type {spec.type}")

    status = ValidationStatus.PASS if ok else ValidationStatus.FAIL
    return _check(name, status, reason)


def validate_offer(
    request: PurchaseRequest,
    offer: OfferEvidence,
    budget_snapshot_minor: int | None = None,
) -> EligibilityResult:
    """Validate a single offer against the request and (optional) budget.

    Checks: category match + mandatory specifications (rule 2), quantity
    sufficiency (rule 3), unknown mandatory information (rule 4), and budget
    ceilings (rule 5). Category attributes are validated generically against the
    catalog spec.
    """
    checks: list[FieldValidation] = []
    req = request.mandatory

    spec = CATEGORIES.get(req.category)
    if req.category == OTHER_CATEGORY:
        # Free-text category: deterministic keyword matching against the
        # offer's extracted specifications. The offer itself is labeled
        # "other" by the extraction, so no category mismatch is possible.
        checks.extend(_keyword_checks(req, offer))
    elif spec is None:
        checks.append(
            _check("category", ValidationStatus.FAIL, f"unknown category {req.category!r}")
        )
    else:
        if offer.category != req.category:
            checks.append(
                _check(
                    "category",
                    ValidationStatus.FAIL,
                    f"offer category {offer.category!r} does not match request {req.category!r}",
                )
            )
        for attr in spec.attributes:
            req_value = req.attributes.get(attr.name)
            if req_value is None:
                # Not requested by the requester; nothing to enforce.
                continue
            checks.append(_attribute_check(attr, req_value, offer.attributes.get(attr.name)))

    # Warranty (universal across categories).
    if req.warranty_months_min is not None:
        if offer.warranty_months is None:
            checks.append(_check("warranty_months", ValidationStatus.UNKNOWN, "warranty not extracted"))
        elif offer.warranty_months >= req.warranty_months_min:
            checks.append(_check("warranty_months", ValidationStatus.PASS, "warranty meets minimum"))
        else:
            checks.append(_check("warranty_months", ValidationStatus.FAIL, "warranty below minimum"))

    # Quantity sufficiency (rule 3): a supplier must cover the entire quantity.
    checks.append(_quantity_check(request, offer))

    # Verified total and budget (rule 5). When shipping is unknown (common on
    # aggregator sites), the total is verified WITHOUT shipping and the check
    # says so — the manager sees the unverified shipping on the approval card.
    total = resolved_total_minor(offer, request.quantity)
    shipping_unverified = offer.shipping_minor is None
    if offer.unit_price_minor is None:
        checks.append(_check("verified_total", ValidationStatus.UNKNOWN, "unit price unresolved"))
        total = None
    elif total is None:
        total = offer.unit_price_minor * request.quantity
        if total > request.max_total_cost_minor:
            checks.append(
                _check("verified_total", ValidationStatus.FAIL, "exceeds request budget (shipping unverified, excluded)")
            )
        else:
            checks.append(
                _check("verified_total", ValidationStatus.PASS, "within budget (shipping unverified, excluded)")
            )
    else:
        if total > request.max_total_cost_minor:
            checks.append(_check("verified_total", ValidationStatus.FAIL, "exceeds request budget"))
        elif budget_snapshot_minor is not None and total > budget_snapshot_minor:
            checks.append(_check("verified_total", ValidationStatus.FAIL, "exceeds department budget snapshot"))
        else:
            checks.append(_check("verified_total", ValidationStatus.PASS, "within budget"))

    # Aggregate status: any FAIL dominates; else any UNKNOWN; else PASS.
    statuses = {c.status for c in checks}
    if ValidationStatus.FAIL in statuses:
        overall = ValidationStatus.FAIL
    elif ValidationStatus.UNKNOWN in statuses:
        overall = ValidationStatus.UNKNOWN
    else:
        overall = ValidationStatus.PASS

    return EligibilityResult(
        offer_id=offer.offer_id,
        status=overall,
        checks=checks,
        verified_total_minor=total,
    )


def _rank_key(item: tuple[OfferEvidence, int]) -> tuple[int, object, str]:
    """Sort key: lowest total, then earlier delivery, then stable supplier id.

    ``date.min`` is used as a sentinel so offers missing a delivery date sort
    after any dated offer without crashing.
    """
    offer, total = item
    delivery = offer.delivery_by if offer.delivery_by is not None else date.min
    return (total, delivery, offer.supplier_id)


def compare_offers(
    request: PurchaseRequest,
    offers: Sequence[OfferEvidence],
    results: Sequence[EligibilityResult],
) -> ComparisonResult:
    """Rank fully eligible offers and select the lowest verified total (rule 8)."""
    eligible: list[tuple[OfferEvidence, int]] = []
    for offer, result in zip(offers, results):
        if result.status is ValidationStatus.PASS and result.verified_total_minor is not None:
            eligible.append((offer, result.verified_total_minor))

    ranked = sorted(eligible, key=_rank_key)
    selected = ranked[0][0].offer_id if ranked else None

    shortfall = len(ranked) < QUOTATION_TARGET

    return ComparisonResult(
        request_id=request.request_id,
        eligible_offers=[o.offer_id for o, _ in eligible],
        ranked_offers=[o.offer_id for o, _ in ranked],
        selected_offer_id=selected,
        quotation_shortfall=shortfall,
    )

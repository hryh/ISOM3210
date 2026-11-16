"""Optional needed-by date + typed-spec extraction in the deep-scrape path."""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from procurement.catalog import OTHER_CATEGORY
from procurement.parsing import ClarificationNeeded, draft_to_request
from procurement.schemas import OfferEvidence, PurchaseRequest, RequestDraft, RequestRequirements


def _request(category: str, attributes: dict, **overrides) -> PurchaseRequest:
    from procurement.schemas import RequestRequirements

    quantity = overrides.pop("quantity", 1)
    max_total = overrides.pop("max_total_minor", 1_000_000)
    deadline = overrides.pop("deadline", None)
    return PurchaseRequest(
        request_id="R",
        requester="t",
        department="d",
        category=category,
        quantity=quantity,
        max_total_cost_minor=max_total,
        deadline=deadline,
        mandatory=RequestRequirements(
            category=category, attributes=attributes, warranty_months_min=None
        ),
        created_at=datetime.now(timezone.utc),
        **overrides,
    )


# --- optional deadline -----------------------------------------------------------


def _draft(**overrides) -> RequestDraft:
    defaults = dict(
        category="monitor",
        quantity=1,
        attributes={"screen_inches_min": 27, "resolution": "2560x1440", "connectors": ["HDMI"]},
        warranty_months_min=None,
        max_total_hkd="5000",
        department="engineering",
    )
    defaults.update(overrides)
    return RequestDraft(**defaults)


def test_request_without_deadline_is_valid():
    request = draft_to_request(_draft(), request_id="R", requester="u")
    assert request.deadline is None


def test_request_with_deadline_still_carries_it():
    request = draft_to_request(_draft(deadline="2026-12-01"), request_id="R", requester="u")
    assert request.deadline == date(2026, 12, 1)


def test_stated_but_unparseable_deadline_asks_for_clarification():
    with pytest.raises(ClarificationNeeded):
        draft_to_request(_draft(deadline="whenever soon"), request_id="R", requester="u")


def test_create_order_without_deadline():
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    from procurement import auth, order_service
    from procurement.repository import Order, init_db, session_factory

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    init_db(engine)
    Session = session_factory(engine)
    with Session() as session:
        user = auth.create_user(
            session, username="u", display_name="U", role="employee", password="pw"
        )
        order = order_service.create_order(
            session,
            requester_id=user.id,
            department="eng",
            category="monitor",
            quantity=1,
            budget_minor=100_000,
            deadline=None,
            requirements={"category": "monitor", "attributes": {}, "warranty_months_min": None},
        )
        assert session.get(Order, order.id).deadline is None


# --- orders table rebuild migration --------------------------------------------------


def test_ensure_columns_makes_orders_deadline_nullable():
    """A DB created when deadline was NOT NULL must be rebuilt, data kept,
    and the order_decisions FK must still resolve afterwards."""
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.pool import StaticPool

    from procurement.repository import _ensure_columns, create_engine_from_url, init_db

    # Build a current-schema DB with one real order, then surgically
    # re-tighten deadline to mimic the old NOT NULL version.
    from procurement import auth, order_service

    engine = create_engine_from_url("sqlite://")
    init_db(engine)
    from procurement.repository import session_factory

    Session = session_factory(engine)
    with Session() as session:
        user = auth.create_user(
            session, username="u", display_name="U", role="employee", password="pw"
        )
        order_service.create_order(
            session,
            requester_id=user.id,
            department="eng",
            category="monitor",
            quantity=1,
            budget_minor=100_000,
            deadline=date(2026, 12, 1),
            requirements={"category": "monitor", "attributes": {}},
        )
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE orders_old (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_no VARCHAR UNIQUE, requester_id INTEGER REFERENCES users (id),
                department VARCHAR, category VARCHAR, quantity INTEGER,
                budget_minor INTEGER, deadline DATE NOT NULL,
                requirements_json TEXT, preferences_json TEXT,
                selected_product_id INTEGER, status VARCHAR, source VARCHAR,
                created_at DATETIME, updated_at DATETIME,
                decided_at DATETIME, placed_at DATETIME
            )
            """
        )
        # Copy an existing row to preserve data through the rebuild.
        conn.exec_driver_sql(
            "INSERT INTO orders_old (order_no, requester_id, department, category, "
            "quantity, budget_minor, deadline, requirements_json, preferences_json, "
            "status, source, created_at, updated_at) "
            "SELECT order_no, requester_id, department, category, quantity, "
            "budget_minor, date('2026-12-01'), requirements_json, preferences_json, "
            "status, source, created_at, updated_at FROM orders"
        )
        conn.exec_driver_sql("DROP TABLE orders")
        conn.exec_driver_sql("ALTER TABLE orders_old RENAME TO orders")

    _ensure_columns(engine)  # must rebuild with nullable deadline

    inspector = inspect(engine)
    deadline_col = next(c for c in inspector.get_columns("orders") if c["name"] == "deadline")
    assert deadline_col["nullable"] is True
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT order_no, deadline FROM orders")).fetchall()
        assert rows and rows[0][1] is not None  # data survived
        # FK integrity: order_decisions still references a resolvable orders table.
        fk_result = conn.execute(text("PRAGMA foreign_key_check")).fetchall()
        assert fk_result == []
    # Idempotent: a second run must not fail.
    _ensure_columns(engine)


# --- typed-spec extraction in the deep-scrape path -----------------------------------


def test_typed_offers_carry_coerced_specs():
    from procurement.tools.suppliers import (
        _ListingProduct,
        _ProductDetails,
        _ShopOffer,
        _shop_offer_to_evidence,
    )

    class _Sup:
        id = 5

    request = _request(
        "monitor",
        {"screen_inches_min": 27, "resolution": "2560x1440", "connectors": ["HDMI", "DisplayPort"]},
    )
    offer = _ShopOffer(shop_name="Centralfield", price_hkd="HK$1,999", stock_state="in_stock")
    details = _ProductDetails(
        specifications="27-inch QHD monitor, HDMI and DisplayPort inputs",
        attributes={
            "screen size (inches)": "27",
            "resolution": "2560x1440",
            "connectors": "HDMI, DisplayPort",
        },
        offers=[offer],
    )
    listing = _ListingProduct(product_name="Dell P2725D", price_hkd="HK$1,999")

    evidence = _shop_offer_to_evidence(
        offer, details, listing, request, _Sup(), datetime.now(timezone.utc)
    )
    assert evidence.attributes["screen_inches_min"] == 27
    assert evidence.attributes["resolution"] == "2560x1440"
    assert evidence.attributes["connectors"] == ["HDMI", "DisplayPort"]
    # Human context kept alongside the typed specs.
    assert evidence.attributes["shop"] == "Centralfield"
    assert evidence.attributes["stock_state"] == "in_stock"
    assert "specifications" in evidence.attributes


def test_typed_offer_passes_validation_end_to_end():
    """The bug this fixes: typed categories via aggregator sites could never
    pass because spec attributes were never extracted."""
    from procurement.rules import validate_offer
    from procurement.tools.suppliers import (
        _ListingProduct,
        _ProductDetails,
        _ShopOffer,
        _shop_offer_to_evidence,
    )

    class _Sup:
        id = 5

    request = _request(
        "monitor",
        {"screen_inches_min": 27, "resolution": "1920x1080", "connectors": ["HDMI"]},
        quantity=2,
        max_total_minor=2_000_000,
    )
    offer = _ShopOffer(shop_name="Shop", price_hkd="HK$819", stock_state="in_stock")
    details = _ProductDetails(
        specifications="27 inch IPS, 16:9 1920X1080, HDMI",
        attributes={"screen size (inches)": "27", "resolution": "1920x1080", "connectors": "HDMI"},
        offers=[offer],
    )
    listing = _ListingProduct(product_name="ASUS VY279HG2", price_hkd="HK$819")

    evidence = _shop_offer_to_evidence(
        offer, details, listing, request, _Sup(), datetime.now(timezone.utc)
    )
    result = validate_offer(request, evidence)
    assert result.status.value == "PASS", [(c.field, c.status.value, c.reason) for c in result.checks]


def test_product_instruction_is_category_aware():
    from procurement.tools.suppliers import _product_instruction

    typed = _request("monitor", {"resolution": "2560x1440"})
    instruction = _product_instruction("Dell P2725D", typed)
    assert "screen size (inches)" in instruction
    assert "1920x1080" in instruction  # canonical choices listed
    assert "normalize" in instruction

    other = _request(OTHER_CATEGORY, {"item": "headphones", "keywords": ["anc"]})
    other_instruction = _product_instruction("Sony WH-1000XM5", other)
    assert "'attributes'" not in other_instruction
    assert "specifications" in other_instruction
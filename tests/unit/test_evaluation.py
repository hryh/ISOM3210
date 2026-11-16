"""Unit tests for rebuilding per-offer verdicts from persisted products."""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from procurement import order_service
from procurement.evaluation import counts, order_verdicts
from procurement.repository import (
    Order,
    Supplier,
    User,
    init_db,
    session_factory,
    upsert_product,
)


def _memory_engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _now():
    return datetime.now(timezone.utc)


GOOD_ATTRS = {
    "screen_inches_min": 27,
    "resolution": "2560x1440",
    "connectors": ["HDMI", "DisplayPort"],
}
BAD_ATTRS = {
    "screen_inches_min": 24,
    "resolution": "1920x1080",
    "connectors": ["HDMI"],
}


def _build_session():
    engine = _memory_engine()
    init_db(engine)
    Session = session_factory(engine)
    session = Session()

    user = User(
        username="alice",
        display_name="Alice",
        role="employee",
        password_hash="x",
        active=True,
        created_at=_now(),
    )
    supplier = Supplier(
        name="Pixel Peak",
        origin="http://127.0.0.1:8100",
        status="approved",
        created_at=_now(),
    )
    session.add_all([user, supplier])
    session.flush()

    order = order_service.create_order(
        session,
        requester_id=user.id,
        department="Engineering",
        category="monitor",
        quantity=2,
        budget_minor=1_000_000,
        deadline=date(2026, 12, 1),
        requirements={
            "category": "monitor",
            "attributes": GOOD_ATTRS,
            "warranty_months_min": 12,
        },
    )
    order_service.submit_order(session, order)

    good = upsert_product(
        session,
        supplier_id=supplier.id,
        product_key="MON_GOOD",
        category="monitor",
        model_name="Vision 27 compliant",
        attributes=GOOD_ATTRS,
        unit_price_minor=300_000,
        shipping_minor=10_000,
        available_quantity=5,
        warranty_months=24,
        delivery_days=3,
        retrieved_at=_now(),
    )
    bad = upsert_product(
        session,
        supplier_id=supplier.id,
        product_key="MON_BAD",
        category="monitor",
        model_name="Vision 24 cheap",
        attributes=BAD_ATTRS,
        unit_price_minor=100_000,
        shipping_minor=10_000,
        available_quantity=5,
        warranty_months=24,
        delivery_days=3,
        retrieved_at=_now(),
    )
    # A stale row from a previous run must be excluded.
    upsert_product(
        session,
        supplier_id=supplier.id,
        product_key="MON_STALE",
        category="monitor",
        model_name="Vision 27 stale",
        attributes=GOOD_ATTRS,
        unit_price_minor=1,
        retrieved_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )

    order.selected_product_id = good.id
    session.commit()
    return session, good, bad


def test_order_verdicts_ranks_and_reports():
    session, good, bad = _build_session()
    order = session.query(Order).one()
    verdicts = order_verdicts(session, order)

    assert [v.product_id for v in verdicts] == [good.id, bad.id]
    top, other = verdicts

    assert top.status == "PASS"
    assert top.recommended is True
    assert top.issues == []
    assert top.total_minor == 300_000 * 2 + 10_000
    assert top.supplier_name == "Pixel Peak"

    assert other.status == "FAIL"
    assert other.recommended is False
    assert other.total_minor == 100_000 * 2 + 10_000
    # Issues use the catalog display names, not raw keys.
    joined = "; ".join(other.issues)
    assert "screen size (inches): below minimum" in joined
    assert "resolution: does not match requirement" in joined


def test_counts_group_by_status():
    session, _, _ = _build_session()
    order = session.query(Order).one()
    assert counts(order_verdicts(session, order)) == {
        "PASS": 1,
        "UNKNOWN": 0,
        "FAIL": 1,
    }
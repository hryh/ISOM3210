from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from procurement import auth, order_service
from procurement.repository import (
    Order,
    OrderDecision,
    init_db,
    session_factory,
)


def _make_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(engine)
    return session_factory(engine)()


def _user(session, username: str, role: str) -> object:
    user = auth.create_user(
        session,
        username=username,
        display_name=username.title(),
        role=role,
        password="pw",
    )
    return user


def _order(session, requester, **overrides) -> Order:
    defaults = dict(
        requester_id=requester.id,
        department="engineering",
        category="monitor",
        quantity=3,
        budget_minor=900_000,
        deadline=date(2026, 11, 30),
        requirements={"category": "monitor", "attributes": {}, "warranty_months_min": None},
        source="wizard",
    )
    defaults.update(overrides)
    return order_service.create_order(session, **defaults)


def _make_pending(session, requester) -> Order:
    order = _order(session, requester)
    order_service.submit_order(session, order)
    order_service.transition(session, order, order_service.OrderStatus.PENDING_APPROVAL)
    return order


def test_order_numbers_are_sequential():
    session = _make_session()
    alice = _user(session, "alice", "employee")
    first = _order(session, alice)
    second = _order(session, alice)
    year = datetime.now(timezone.utc).year
    assert first.order_no == f"PO-{year}-0001"
    assert second.order_no == f"PO-{year}-0002"


def test_illegal_transitions_rejected():
    session = _make_session()
    alice = _user(session, "alice", "employee")
    order = _order(session, alice)
    with pytest.raises(order_service.TransitionError):
        order_service.transition(session, order, order_service.OrderStatus.PLACED)


def test_happy_path_lifecycle():
    session = _make_session()
    alice = _user(session, "alice", "employee")
    manager = _user(session, "m", "manager")

    order = _make_pending(session, alice)
    order_service.approve_order(session, order, manager)

    assert order.status == order_service.OrderStatus.PLACED.value
    assert order.decided_at is not None
    assert order.placed_at is not None

    decisions = session.query(OrderDecision).filter_by(order_id=order.id).all()
    assert [d.decision for d in decisions] == ["approved"]


def test_only_managers_approve():
    session = _make_session()
    alice = _user(session, "alice", "employee")
    bob = _user(session, "bob", "employee")
    order = _make_pending(session, alice)
    with pytest.raises(order_service.PermissionError_):
        order_service.approve_order(session, order, bob)


def test_rejection_requires_reason():
    session = _make_session()
    alice = _user(session, "alice", "employee")
    manager = _user(session, "m", "manager")
    order = _make_pending(session, alice)
    with pytest.raises(ValueError):
        order_service.reject_order(session, order, manager, "   ")
    order_service.reject_order(session, order, manager, "over budget")
    assert order.status == order_service.OrderStatus.REJECTED.value
    decisions = session.query(OrderDecision).filter_by(order_id=order.id).all()
    assert decisions[0].reason == "over budget"


def test_requester_can_cancel_own_draft():
    session = _make_session()
    alice = _user(session, "alice", "employee")
    order = _order(session, alice)
    order_service.cancel_order(session, order, alice, "changed my mind")
    assert order.status == order_service.OrderStatus.CANCELLED.value


def test_other_employee_cannot_cancel():
    session = _make_session()
    alice = _user(session, "alice", "employee")
    bob = _user(session, "bob", "employee")
    order = _order(session, alice)
    with pytest.raises(order_service.PermissionError_):
        order_service.cancel_order(session, order, bob)


def test_manager_can_cancel_others():
    session = _make_session()
    alice = _user(session, "alice", "employee")
    manager = _user(session, "m", "manager")
    order = _order(session, alice)
    order_service.cancel_order(session, order, manager)
    assert order.status == order_service.OrderStatus.CANCELLED.value


def test_terminal_cannot_cancel():
    session = _make_session()
    alice = _user(session, "alice", "employee")
    manager = _user(session, "m", "manager")
    order = _make_pending(session, alice)
    order_service.approve_order(session, order, manager)
    with pytest.raises(order_service.TransitionError):
        order_service.cancel_order(session, order, manager)


def test_pending_approvals_listing():
    session = _make_session()
    alice = _user(session, "alice", "employee")
    manager = _user(session, "m", "manager")

    pending = _make_pending(session, alice)
    placed = _make_pending(session, alice)
    order_service.approve_order(session, placed, manager)

    listed = order_service.pending_approvals(session)
    assert [o.id for o in listed] == [pending.id]


def test_discard_draft_deletes_row():
    session = _make_session()
    alice = _user(session, "alice", "employee")
    order = _order(session, alice)
    order_service.discard_draft(session, order)
    assert session.get(Order, order.id) is None

    submitted = _make_pending(session, alice)
    with pytest.raises(order_service.TransitionError):
        order_service.discard_draft(session, submitted)


def test_user_drafts_scoped_to_requester():
    session = _make_session()
    alice = _user(session, "alice", "employee")
    bob = _user(session, "bob", "employee")
    _order(session, alice)
    _order(session, alice)
    _order(session, bob)

    assert len(order_service.user_drafts(session, alice.id)) == 2
    assert len(order_service.user_drafts(session, bob.id)) == 1
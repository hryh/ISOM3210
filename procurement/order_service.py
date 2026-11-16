"""Order lifecycle service.

The single authority for order status transitions and human decisions. All
UI pages and the research orchestrator go through these functions — never raw
UPDATEs — so the lifecycle map below is always enforced.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum

from sqlalchemy import select
from sqlalchemy.orm import Session

from .repository import Order, OrderDecision, Product, Supplier, User


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    RESEARCHING = "RESEARCHING"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    PLACED = "PLACED"
    REJECTED = "REJECTED"
    NO_OFFER = "NO_OFFER"
    CANCELLED = "CANCELLED"


TERMINAL_STATUSES = frozenset(
    {
        OrderStatus.PLACED,
        OrderStatus.REJECTED,
        OrderStatus.NO_OFFER,
        OrderStatus.CANCELLED,
    }
)

ALLOWED_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.DRAFT: frozenset(
        {OrderStatus.RESEARCHING, OrderStatus.CANCELLED}
    ),
    OrderStatus.RESEARCHING: frozenset(
        {OrderStatus.PENDING_APPROVAL, OrderStatus.NO_OFFER, OrderStatus.CANCELLED}
    ),
    OrderStatus.PENDING_APPROVAL: frozenset(
        {OrderStatus.APPROVED, OrderStatus.REJECTED, OrderStatus.CANCELLED}
    ),
    OrderStatus.APPROVED: frozenset({OrderStatus.PLACED}),
    OrderStatus.PLACED: frozenset(),
    OrderStatus.REJECTED: frozenset(),
    OrderStatus.NO_OFFER: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
}


class TransitionError(ValueError):
    """Raised when an illegal status transition is attempted."""


class PermissionError_(PermissionError):
    """Raised when the acting user may not perform the action."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def next_order_no(session: Session) -> str:
    """Sequential, human-friendly order number: ``PO-YYYY-0001``."""
    year = datetime.now(timezone.utc).year
    prefix = f"PO-{year}-"
    stmt = select(Order.order_no).where(Order.order_no.like(f"{prefix}%"))
    highest = 0
    for (order_no,) in session.execute(stmt):
        try:
            highest = max(highest, int(order_no[len(prefix):]))
        except ValueError:  # pragma: no cover - defensive
            continue
    return f"{prefix}{highest + 1:04d}"


def create_order(
    session: Session,
    *,
    requester_id: int,
    department: str,
    category: str,
    quantity: int,
    budget_minor: int,
    deadline: date | None,
    requirements: dict,
    preferences: dict | None = None,
    source: str = "wizard",
) -> Order:
    """Create a DRAFT order. The wizard autosaves through this; chat confirms through it too."""
    now = _now()
    order = Order(
        order_no=next_order_no(session),
        requester_id=requester_id,
        department=department,
        category=category,
        quantity=quantity,
        budget_minor=budget_minor,
        deadline=deadline,
        requirements_json=json.dumps(requirements, ensure_ascii=False),
        preferences_json=json.dumps(preferences or {}, ensure_ascii=False),
        status=OrderStatus.DRAFT.value,
        source=source,
        created_at=now,
        updated_at=now,
    )
    session.add(order)
    session.commit()
    session.refresh(order)
    return order


def get_order(session: Session, order_id: int) -> Order | None:
    return session.get(Order, order_id)


def transition(
    session: Session, order: Order, new_status: OrderStatus
) -> Order:
    """Validate and apply a status transition."""
    current = OrderStatus(order.status)
    if new_status not in ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise TransitionError(f"illegal transition {current.value} -> {new_status.value}")
    order.status = new_status.value
    order.updated_at = _now()
    session.commit()
    session.refresh(order)
    return order


def submit_order(session: Session, order: Order) -> Order:
    """DRAFT -> RESEARCHING. Kicks off the agent blackbox (caller starts the thread)."""
    return transition(session, order, OrderStatus.RESEARCHING)


def update_draft_order(
    session: Session,
    order: Order,
    *,
    department: str,
    category: str,
    quantity: int,
    budget_minor: int,
    deadline: date | None,
    requirements: dict,
    preferences: dict | None = None,
) -> Order:
    """Overwrite a DRAFT order's details (wizard autosave)."""
    if order.status != OrderStatus.DRAFT.value:
        raise TransitionError("only DRAFT orders can be edited")
    order.department = department
    order.category = category
    order.quantity = quantity
    order.budget_minor = budget_minor
    order.deadline = deadline
    order.requirements_json = json.dumps(requirements, ensure_ascii=False)
    order.preferences_json = json.dumps(preferences or {}, ensure_ascii=False)
    order.updated_at = _now()
    session.commit()
    session.refresh(order)
    return order


def discard_draft(session: Session, order: Order) -> None:
    """Delete an unfinished DRAFT order outright (no decision record)."""
    if order.status != OrderStatus.DRAFT.value:
        raise TransitionError("only DRAFT orders can be discarded")
    session.delete(order)
    session.commit()


def _record_decision(
    session: Session,
    order: Order,
    *,
    decision: str,
    user: User,
    reason: str | None,
) -> OrderDecision:
    record = OrderDecision(
        order_id=order.id,
        decision=decision,
        decided_by=user.id,
        role=user.role,
        reason=(reason or None),
        decided_at=_now(),
    )
    session.add(record)
    return record


def approve_order(
    session: Session, order: Order, manager: User, reason: str | None = None
) -> Order:
    """Manager approves: PENDING_APPROVAL -> APPROVED -> PLACED.

    The PLACED step marks the requisition as submitted to the supplier (the
    real portal submission is a Phase 4 stub inside the blackbox).
    """
    if manager.role != "manager":
        raise PermissionError_("only managers can approve orders")
    _record_decision(session, order, decision="approved", user=manager, reason=reason)
    order.decided_at = _now()
    transition(session, order, OrderStatus.APPROVED)
    order.placed_at = _now()
    return transition(session, order, OrderStatus.PLACED)


def reject_order(session: Session, order: Order, manager: User, reason: str) -> Order:
    """Manager rejects: PENDING_APPROVAL -> REJECTED. A reason is mandatory."""
    if manager.role != "manager":
        raise PermissionError_("only managers can reject orders")
    if not reason or not reason.strip():
        raise ValueError("a reason is required to reject an order")
    _record_decision(
        session, order, decision="rejected", user=manager, reason=reason.strip()
    )
    order.decided_at = _now()
    return transition(session, order, OrderStatus.REJECTED)


def cancel_order(
    session: Session, order: Order, user: User, reason: str | None = None
) -> Order:
    """Requester cancels their own order; managers can cancel any active order."""
    if OrderStatus(order.status) in TERMINAL_STATUSES:
        raise TransitionError(f"order is already terminal: {order.status}")
    if user.role != "manager" and order.requester_id != user.id:
        raise PermissionError_("only the requester or a manager can cancel an order")
    _record_decision(session, order, decision="cancelled", user=user, reason=reason)
    order.decided_at = _now()
    return transition(session, order, OrderStatus.CANCELLED)


def pending_approvals(session: Session) -> list[Order]:
    stmt = (
        select(Order)
        .where(Order.status == OrderStatus.PENDING_APPROVAL.value)
        .order_by(Order.updated_at.desc())
    )
    return list(session.scalars(stmt))


@dataclass
class OrderView:
    """Everything the history/detail UI renders for one order."""

    order: Order
    requester: User | None
    product: Product | None
    supplier: Supplier | None
    decisions: list[OrderDecision]

    @property
    def total_minor(self) -> int | None:
        """Verified total, mirroring the rules engine's semantics: unit price
        × quantity plus shipping when known, excluding shipping when the site
        did not list it (the card shows the gap)."""
        if self.product is None or self.product.unit_price_minor is None:
            return None
        total = self.product.unit_price_minor * self.order.quantity
        if self.product.shipping_minor is not None:
            total += self.product.shipping_minor
        return total


def order_view(session: Session, order: Order) -> OrderView:
    return OrderView(
        order=order,
        requester=session.get(User, order.requester_id),
        product=(
            session.get(Product, order.selected_product_id)
            if order.selected_product_id
            else None
        ),
        supplier=(
            session.get(Supplier, session.get(Product, order.selected_product_id).supplier_id)
            if order.selected_product_id
            and session.get(Product, order.selected_product_id)
            else None
        ),
        decisions=list(
            session.scalars(
                select(OrderDecision)
                .where(OrderDecision.order_id == order.id)
                .order_by(OrderDecision.decided_at)
            )
        ),
    )


def list_orders(
    session: Session,
    *,
    status: str | None = None,
    category: str | None = None,
    requester_id: int | None = None,
) -> list[Order]:
    stmt = select(Order).order_by(Order.created_at.desc())
    if status:
        stmt = stmt.where(Order.status == status)
    if category:
        stmt = stmt.where(Order.category == category)
    if requester_id:
        stmt = stmt.where(Order.requester_id == requester_id)
    return list(session.scalars(stmt))


def user_drafts(session: Session, user_id: int) -> list[Order]:
    """A user's resumable DRAFT orders."""
    stmt = (
        select(Order)
        .where(
            Order.status == OrderStatus.DRAFT.value,
            Order.requester_id == user_id,
        )
        .order_by(Order.updated_at.desc())
    )
    return list(session.scalars(stmt))
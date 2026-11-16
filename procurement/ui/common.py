"""Shared UI helpers: status badges, order status widget, guards."""

from __future__ import annotations

import json
import time

import streamlit as st

from .. import order_service
from ..catalog import CATEGORIES, OTHER_CATEGORY
from ..money import format_hkd
from ..repository import session_factory

#: (css class, human label) per order status. Color never carries the meaning
#: alone — every badge renders a text label.
STATUS_META: dict[str, tuple[str, str]] = {
    "DRAFT": ("draft", "Draft"),
    "RESEARCHING": ("researching", "Researching"),
    "PENDING_APPROVAL": ("pending", "Pending approval"),
    "APPROVED": ("success", "Approved"),
    "PLACED": ("success", "Placed"),
    "REJECTED": ("danger", "Rejected"),
    "NO_OFFER": ("danger", "No offer"),
    "CANCELLED": ("cancelled", "Cancelled"),
}

_SUPPLIER_STATUS_META = {"approved": ("success", "Approved"), "blocked": ("danger", "Blocked")}


def status_badge(status: str) -> str:
    """Render a status pill. Returns inline HTML for st.markdown blocks."""
    css, label = STATUS_META.get(status, ("neutral", status.replace("_", " ").title()))
    return f'<span class="pp-badge pp-badge--{css}">{label}</span>'


def supplier_status_badge(status: str) -> str:
    css, label = _SUPPLIER_STATUS_META.get(status, ("neutral", status.title()))
    return f'<span class="pp-badge pp-badge--{css}">{label}</span>'


def role_badge(role: str) -> str:
    return f'<span class="pp-badge pp-badge--neutral">{role.title()}</span>'


def status_label(status: str) -> str:
    """Plain-text label (for dataframe cells and selectboxes)."""
    return STATUS_META.get(status, (None, status.replace("_", " ").title()))[1]


def require_manager(user: dict) -> None:
    """Stop rendering the page when the current user is not a manager."""
    if user["role"] != "manager":
        st.error(
            "Approving and managing the app needs a manager account. "
            "Ask a manager to handle this for you."
        )
        st.stop()


def order_status_line(order) -> str:
    return f"{order.order_no} &nbsp; {status_badge(order.status)}"


def render_order_status(engine, order_id: int, poll_seconds: int = 30) -> None:
    """Live status panel for an in-flight order.

    Auto-polls for up to ``poll_seconds`` while the agent is researching, then
    falls back to a manual refresh button. Never blocks longer than that.
    """
    Session = session_factory(engine)
    with Session() as session:
        order = order_service.get_order(session, order_id)
    if order is None:
        st.warning("Order not found.")
        return

    ph = st.empty()
    deadline = time.time() + poll_seconds
    while (
        order.status == order_service.OrderStatus.RESEARCHING.value
        and time.time() < deadline
    ):
        ph.info(f"{order.order_no}: the agent is researching suppliers…")
        time.sleep(5)
        with Session() as session:
            order = order_service.get_order(session, order_id)

    if order.status == order_service.OrderStatus.RESEARCHING.value:
        ph.info(f"{order.order_no}: still researching — check again in a moment.")
        if st.button("Refresh status"):
            st.rerun()
        return

    _render_terminal_status(ph, engine, order_id, order.status)


def _render_terminal_status(ph, engine, order_id: int, status: str) -> None:
    if status == order_service.OrderStatus.PENDING_APPROVAL.value:
        ph.success(
            f"{status_label(status)}: the agent found a compliant offer — "
            "a manager can review it under Pending Approvals."
        )
    elif status == order_service.OrderStatus.NO_OFFER.value:
        ph.error(
            f"{status_label(status)}: no compliant offer was found. "
            "Edit the request and submit it again from Order Request or the chat."
        )
    else:
        ph.markdown(status_badge(status), unsafe_allow_html=True)


def _format_value(value) -> str:
    """Human formatting for requirement values: no raw Python repr."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    return str(value)


def pretty_requirements(requirements_json: str | None) -> str:
    """Human-readable rendering of the stored requirements JSON.

    Uses the catalog's display names (not raw attribute keys) and formats
    values for reading — booleans become Yes/No, lists become comma phrases.
    Free-text ("other") requests render the item and keyword list.
    """
    if not requirements_json:
        return "—"
    try:
        data = json.loads(requirements_json)
    except json.JSONDecodeError:
        return "—"
    category = data.get("category")
    spec = CATEGORIES.get(category) if category else None

    lines: list[str] = []
    attributes = data.get("attributes") or {}
    if category == OTHER_CATEGORY:
        item = attributes.get("item")
        if item:
            lines.append(f"- **Item:** {_format_value(item)}")
        keywords = attributes.get("keywords") or []
        if keywords:
            lines.append(
                "- **Required keywords:** " + _format_value(keywords)
            )
    else:
        for attr in (spec.attributes if spec else []):
            if attr.name in attributes and attributes[attr.name] is not None:
                lines.append(f"- **{attr.display_name}:** {_format_value(attributes[attr.name])}")
        # Attributes not in the catalog spec (defensive) still render readable.
        for key, value in attributes.items():
            if spec is None or key not in spec.attribute_map:
                if value is not None:
                    lines.append(f"- **{key.replace('_', ' ')}:** {_format_value(value)}")

    warranty = data.get("warranty_months_min")
    if warranty:
        lines.append(f"- **Minimum warranty:** {warranty} months")

    return "\n".join(lines) if lines else "—"


def hkd(minor: int | None) -> str:
    return format_hkd(minor) if minor is not None else "—"
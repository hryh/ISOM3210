"""Page — Contact Sellers (managers only).

After a manager approves an order it is PLACED. From here the manager can ask
the seller-contact routine to draft a WhatsApp message to the seller. The
routine asks the manager to approve the message before anything is sent, and
it only receives the order number, never the order details.

Read-only on orders: this page never changes an order's status.
"""

from __future__ import annotations

import streamlit as st

from .. import order_service
from ..repository import session_factory
from ..tools.seller_contact import (
    AUTH_ENV,
    URL_ENV,
    contact_configured,
    latest_contacts,
    record_contact,
    request_whatsapp_draft,
)
from .common import hkd, require_manager, status_badge


def _contact(order_no: str, manager_name: str) -> None:
    with st.spinner("Asking the routine to draft the WhatsApp message…"):
        result = request_whatsapp_draft(order_no)
    record_contact(result, manager=manager_name)


def render(engine, user: dict) -> None:
    require_manager(user)
    st.title("Contact Sellers")
    st.caption(
        "Approved orders. Request a WhatsApp draft to the seller; you approve the "
        "message where the routine asks you, and nothing is sent until you do. "
        "Only the order number is shared with the routine."
    )

    if not contact_configured():
        st.info(
            f"Seller contact isn't set up on this server. Add `{URL_ENV}` and "
            f"`{AUTH_ENV}` to `.env` (local) or the app's Secrets (Streamlit Cloud)."
        )

    Session = session_factory(engine)
    with Session() as session:
        placed = order_service.list_orders(
            session, status=order_service.OrderStatus.PLACED.value
        )
        views = [order_service.order_view(session, o) for o in placed]

    if not views:
        st.info("No approved orders yet. Approve one on Pending Approvals first.")
        return

    if st.button("Refresh"):
        st.rerun()

    contacts = latest_contacts()
    for view in views:
        order = view.order
        last = contacts.get(order.order_no)
        with st.container(border=True):
            st.markdown(
                f"### {order.order_no} &nbsp; {status_badge(order.status)}",
                unsafe_allow_html=True,
            )
            st.markdown(
                f"- **Supplier:** {view.supplier.name if view.supplier else '—'}\n"
                f"- **Product:** "
                f"{(view.product.model_name or view.product.product_key) if view.product else '—'}\n"
                f"- **Quantity:** {order.quantity} &nbsp;·&nbsp; **Total:** {hkd(view.total_minor)}"
            )

            if last and last["status"] == "sent":
                st.success(
                    f"Draft requested by {last['manager']} at {last['at']} (UTC). "
                    "Approve the message where the routine asks you."
                )
                continue

            if last:
                hint = (
                    " Check whether the approval request arrived before trying again."
                    if last["status"] == "uncertain"
                    else ""
                )
                st.warning(f"Last attempt: {last['detail']}{hint}")

            label = "Try again" if last else "Contact seller on WhatsApp"
            if st.button(
                label,
                key=f"contact_seller_{order.id}",
                type="primary",
                disabled=not contact_configured(),
            ):
                _contact(order.order_no, user["display_name"])
                st.rerun()

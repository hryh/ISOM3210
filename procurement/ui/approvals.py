"""Page 3 — Pending Approvals: the manager's dedicated decision view.

Approve/reject lives here and nowhere else. Rejecting requires a reason. Every
decision is written to ``order_decisions`` (the human decision trail).
"""

from __future__ import annotations

import streamlit as st

from .. import order_service
from ..repository import User, session_factory
from .common import hkd, pretty_requirements, require_manager, status_badge


def _approve(engine, user: dict, order_id: int) -> None:
    Session = session_factory(engine)
    with Session() as session:
        fresh = order_service.get_order(session, order_id)
        manager = session.get(User, user["id"])
        try:
            order_service.approve_order(session, fresh, manager)
        except (
            order_service.TransitionError,
            order_service.PermissionError_,
        ) as exc:
            st.error(f"Could not approve: {exc}")
            st.stop()
    st.success("Order approved and placed.")
    st.rerun()


def _reject(engine, user: dict, order_id: int, reason: str) -> None:
    Session = session_factory(engine)
    with Session() as session:
        fresh = order_service.get_order(session, order_id)
        manager = session.get(User, user["id"])
        try:
            order_service.reject_order(session, fresh, manager, reason)
        except (
            ValueError,
            order_service.TransitionError,
            order_service.PermissionError_,
        ) as exc:
            st.error(f"Could not reject: {exc}")
            st.stop()
    st.rerun()


def render(engine, user: dict) -> None:
    require_manager(user)
    st.title("Pending Approvals")
    st.caption("Orders where the agent found a compliant offer, awaiting your decision.")

    Session = session_factory(engine)
    with Session() as session:
        pending = order_service.pending_approvals(session)

    if not pending:
        st.success("Nothing pending — all caught up. 🎉")
        return

    for order in pending:
        Session = session_factory(engine)
        with Session() as session:
            order = order_service.get_order(session, order.id)  # fresh copy
            view = order_service.order_view(session, order)
            product = view.product
            supplier = view.supplier

            with st.container(border=True):
                st.markdown(
                    f"### {order.order_no} &nbsp; {status_badge(order.status)}",
                    unsafe_allow_html=True,
                )
                col1, col2 = st.columns(2)

                with col1:
                    st.markdown("**Requested**")
                    st.markdown(pretty_requirements(order.requirements_json))
                    st.markdown(
                        f"- **Quantity:** {order.quantity}\n"
                        f"- **Budget (max):** {hkd(order.budget_minor)}\n"
                        f"- **Deadline:** {order.deadline}\n"
                        f"- **Requester:** "
                        f"{view.requester.display_name if view.requester else '—'} "
                        f"({order.department})\n"
                        f"- **Source:** {order.source}"
                    )

                with col2:
                    st.markdown("**Best compliant offer**")
                    if product is None:  # pragma: no cover - defensive
                        st.warning("No product selected on this order.")
                    else:
                        over = ""
                        if (
                            view.total_minor is not None
                            and view.total_minor > order.budget_minor
                        ):
                            over = " (over budget)"
                        st.markdown(
                            f"- **Supplier:** "
                            f"{supplier.name if supplier else '—'}\n"
                            f"- **Product:** "
                            f"{product.model_name or product.product_key}\n"
                            f"- **Unit price:** {hkd(product.unit_price_minor)}\n"
                            f"- **Shipping:** {hkd(product.shipping_minor)}\n"
                            f"- **Total ({order.quantity} units):** "
                            f"{hkd(view.total_minor)}{over}\n"
                            f"- **Warranty:** "
                            f"{product.warranty_months or '—'} months\n"
                            f"- **Delivery:** "
                            f"{product.delivery_days if product.delivery_days is not None else '—'} days"
                        )

                act1, act2 = st.columns(2)
                if act1.button("Approve", key=f"approve_{order.id}", type="primary"):
                    _approve(engine, user, order.id)

                rejecting = st.session_state.get(f"rejecting_{order.id}", False)
                if act2.button("Reject order", key=f"reject_{order.id}"):
                    st.session_state[f"rejecting_{order.id}"] = True
                    st.rerun()

                if rejecting:
                    with st.form(f"reject_form_{order.id}"):
                        reason = st.text_area(
                            "Reason (required)", key=f"reject_reason_{order.id}"
                        )
                        submitted = st.form_submit_button("Confirm rejection")
                    if submitted:
                        st.session_state.pop(f"rejecting_{order.id}", None)
                        _reject(engine, user, order.id, reason)
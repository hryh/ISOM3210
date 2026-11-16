"""Page 2 — All Orders: read-only history for everyone.

Table of all orders with filters and a detail view including the decision
trail. No action buttons by design — approvals live on their own page.
"""

from __future__ import annotations

import streamlit as st

from .. import order_service
from ..repository import session_factory
from .common import hkd, pretty_requirements, status_badge, status_label


def render(engine, user: dict) -> None:
    st.title("All Orders")
    st.caption("Read-only history of every order request — everyone sees all orders.")

    Session = session_factory(engine)
    with Session() as session:
        orders = order_service.list_orders(session)

    if not orders:
        st.info(
            "No orders yet. Create one from the Chatbot or the Order Request page."
        )
        return

    # ---- filters ------------------------------------------------------------
    status_map = {s.value: status_label(s.value) for s in order_service.OrderStatus}
    categories = sorted({o.category for o in orders if o.category})
    col1, col2, col3 = st.columns(3)
    status_filter = col1.selectbox(
        "Status",
        ["All", *status_map.keys()],
        format_func=lambda v: "All" if v == "All" else status_map[v],
    )
    category_filter = col2.selectbox("Category", ["All", *categories])
    if col3.button("Refresh"):
        st.rerun()

    def _keep(o) -> bool:
        if status_filter != "All" and o.status != status_filter:
            return False
        if category_filter != "All" and o.category != category_filter:
            return False
        return True

    orders = [o for o in orders if _keep(o)]
    if not orders:
        st.info("No orders match these filters. Clear them to see all orders.")
        return

    # ---- summary table ------------------------------------------------------
    Session = session_factory(engine)
    with Session() as session:
        rows = []
        for o in orders:
            view = order_service.order_view(session, o)
            rows.append(
                {
                    "Order": o.order_no,
                    "Status": status_label(o.status),
                    "Category": o.category,
                    "Qty": o.quantity,
                    "Budget": hkd(o.budget_minor),
                    "Supplier": view.supplier.name if view.supplier else "—",
                    "Product": view.product.model_name if view.product else "—",
                    "Total": hkd(view.total_minor),
                    "Requester": (
                        view.requester.display_name if view.requester else "—"
                    ),
                    "Department": o.department,
                    "Updated": o.updated_at.strftime("%Y-%m-%d %H:%M"),
                }
            )

    st.table(rows)

    # ---- detail view ----------------------------------------------------------
    st.subheader("Order details")
    order_nos = [o.order_no for o in orders]
    picked = st.selectbox("Select an order", order_nos)
    order = next(o for o in orders if o.order_no == picked)
    Session = session_factory(engine)
    with Session() as session:
        view = order_service.order_view(session, order)

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
            f"- **Source:** {order.source}\n"
            f"- **Created:** {order.created_at.strftime('%Y-%m-%d %H:%M')}"
        )
    with col2:
        st.markdown("**Selected offer**")
        if view.product is None:
            st.markdown("— (none selected yet)")
        else:
            st.markdown(
                f"- **Supplier:** {view.supplier.name if view.supplier else '—'}\n"
                f"- **Product:** {view.product.model_name or view.product.product_key}\n"
                f"- **Unit price:** {hkd(view.product.unit_price_minor)}\n"
                f"- **Shipping:** {hkd(view.product.shipping_minor)}\n"
                f"- **Total ({order.quantity} units):** {hkd(view.total_minor)}\n"
                f"- **Warranty:** "
                f"{view.product.warranty_months or '—'} months\n"
                f"- **Delivery:** "
                f"{view.product.delivery_days if view.product.delivery_days is not None else '—'} days"
            )

    if view.decisions:
        st.markdown("**Decision trail**")
        for d in view.decisions:
            st.markdown(
                f"- {d.decided_at.strftime('%Y-%m-%d %H:%M')} — "
                f"**{d.decision.title()}** by a {d.role}"
                + (f" — {d.reason}" if d.reason else "")
            )
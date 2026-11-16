"""Page 4 — Suppliers: the agent's approved browsing list.

Suppliers are added manually by managers; the agent researches exactly these
sites (their ``origin``) during order requests. Adding a live supplier URL here
is all it takes to move off the mock world. Employees get a read-only view.
"""

from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

from ..repository import Product, Supplier, User, session_factory
from .common import hkd, supplier_status_badge


def render(engine, user: dict) -> None:
    st.title("Suppliers")
    st.caption(
        "Approved supplier sites the agent browses during order requests. "
        "Managers add and manage suppliers; later, add live supplier URLs here "
        "to research real sites."
    )
    is_manager = user["role"] == "manager"

    # ---- add supplier (manager) ---------------------------------------------
    if is_manager:
        with st.expander("Add a supplier"):
            with st.form("add_supplier_form"):
                name = st.text_input("Supplier name")
                origin = st.text_input(
                    "Site URL (origin)",
                    help="The base URL the agent starts browsing from.",
                )
                catalog_url = st.text_input(
                    "Catalog / search URL (optional, for aggregator sites)",
                    help=(
                        "Direct entry point for research. Use {query} where the "
                        "search phrase goes, e.g. "
                        "https://www.price.com.hk/search.php?keyword={query}"
                    ),
                )
                notes = st.text_area("Notes (optional)")
                submitted = st.form_submit_button("Add supplier", type="primary")
            if submitted:
                Session = session_factory(engine)
                with Session() as session:
                    try:
                        if not name.strip() or not origin.strip():
                            raise ValueError("name and site URL are required")
                        if (
                            session.query(Supplier)
                            .filter_by(name=name.strip())
                            .one_or_none()
                            is not None
                        ):
                            raise ValueError(f"{name.strip()!r} already exists")
                        admin = session.get(User, user["id"])
                        session.add(
                            Supplier(
                                name=name.strip(),
                                origin=origin.strip(),
                                catalog_url=catalog_url.strip() or None,
                                status="approved",
                                added_by=admin.id,
                                notes=notes.strip() or None,
                                created_at=datetime.now(timezone.utc),
                            )
                        )
                        session.commit()
                    except ValueError as exc:
                        st.error(f"Could not add supplier: {exc}")
                    else:
                        st.rerun()

    # ---- supplier list ---------------------------------------------------------
    Session = session_factory(engine)
    with Session() as session:
        suppliers = list(session.query(Supplier).order_by(Supplier.created_at.desc()))
        if not suppliers:
            st.info("No suppliers yet. Managers can add one above.")
            return

        for sup in suppliers:
            products = list(session.query(Product).filter_by(supplier_id=sup.id))
            added_by = session.get(User, sup.added_by) if sup.added_by else None
            with st.expander(
                f"{sup.name} — {len(products)} "
                f"{'product' if len(products) == 1 else 'products'}"
            ):
                st.markdown(
                    f"- **Status:** {supplier_status_badge(sup.status)}\n"
                    f"- **Site:** {sup.origin}\n"
                    + (
                        f"- **Catalog URL:** {sup.catalog_url}\n"
                        if sup.catalog_url
                        else ""
                    )
                    + f"- **Added by:** "
                    f"{added_by.display_name if added_by else '—'}\n"
                    f"- **Added:** "
                    f"{sup.created_at.strftime('%Y-%m-%d')}"
                    + (f"\n- **Notes:** {sup.notes}" if sup.notes else ""),
                    unsafe_allow_html=True,
                )

                if is_manager:
                    col1, col2 = st.columns(2)
                    if col1.button(
                        "Block supplier" if sup.status == "approved" else "Approve supplier",
                        key=f"toggle_{sup.id}",
                    ):
                        Session2 = session_factory(engine)
                        with Session2() as s2:
                            row = s2.get(Supplier, sup.id)
                            row.status = (
                                "blocked" if row.status == "approved" else "approved"
                            )
                            s2.commit()
                        st.rerun()

                    can_delete = not products
                    if can_delete:
                        # Destructive action: the confirmation lives inside the
                        # popover, so one stray click can never delete.
                        with col2.popover("Delete supplier", use_container_width=True):
                            st.caption(
                                f"Permanently delete {sup.name} from the agent's "
                                "supplier list."
                            )
                            if st.button(
                                "Delete permanently", key=f"delete_{sup.id}"
                            ):
                                Session2 = session_factory(engine)
                                with Session2() as s2:
                                    s2.delete(s2.get(Supplier, sup.id))
                                    s2.commit()
                                st.rerun()
                    else:
                        col2.caption(
                            "Suppliers with saved products cannot be deleted."
                        )

                if products:
                    rows = [
                        {
                            "Product": p.model_name or p.product_key,
                            "Category": p.category,
                            "Unit price": hkd(p.unit_price_minor),
                            "Shipping": hkd(p.shipping_minor),
                            "Stock": p.available_quantity,
                            "Warranty (mo)": p.warranty_months,
                            "Delivery (days)": p.delivery_days,
                            "Last seen": p.last_seen_at.strftime("%Y-%m-%d %H:%M"),
                        }
                        for p in products
                    ]
                    st.table(rows)
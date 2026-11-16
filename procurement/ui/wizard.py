"""Page 1 — Order Request: a stage-by-stage wizard.

Four steps prompt for one thing at a time instead of a wall-of-form: category,
dynamic specs (driven by the catalog), commercial terms, review. Progress is
autosaved as a DRAFT order so a half-finished request survives a refresh.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import streamlit as st

from .. import order_service
from ..catalog import CATEGORIES, OTHER_CATEGORY
from ..repository import session_factory
from ..research import start_research_thread
from .common import pretty_requirements, render_order_status, status_badge

STEPS = ["Category", "Specifications", "Commercial terms", "Review & submit"]


def _reset_wizard() -> None:
    st.session_state.wizard_step = 0
    st.session_state.wizard = {}
    st.session_state.wizard_order_id = None


def _attribute_widget(attr, key: str):
    """Render one catalog attribute as the widget that fits its type."""
    if attr.choices is not None:
        options = list(attr.choices)
        if attr.type == "list":
            picked = st.multiselect(
                f"{attr.display_name} (choose all required)",
                options,
                default=st.session_state.wizard.get(key) or [],
                key=f"wizard_field_{key}",
            )
            return picked or None
        default = st.session_state.wizard.get(key)
        default = default if default in options else options[0]
        return st.selectbox(
            attr.display_name, options, index=options.index(default), key=f"wizard_field_{key}"
        )
    if attr.type == "int":
        value = st.session_state.wizard.get(key)
        return st.number_input(
            f"{attr.display_name} (minimum)",
            min_value=0,
            value=int(value) if value is not None else 0,
            key=f"wizard_field_{key}",
        )
    if attr.type == "bool":
        return st.toggle(
            attr.display_name,
            value=bool(st.session_state.wizard.get(key)),
            key=f"wizard_field_{key}",
        )
    value = st.session_state.wizard.get(key) or ""
    return st.text_input(attr.display_name, value=value, key=f"wizard_field_{key}") or None


def _capture_attribute_values(category: str) -> dict:
    """Copy the rendered widget outputs back into the wizard state."""
    spec = CATEGORIES[category]
    values = {}
    for attr in spec.attributes:
        widget_key = f"wizard_field_{attr.name}"
        if widget_key in st.session_state:
            values[attr.name] = st.session_state[widget_key]
    return values


def _save_autosave(engine, user: dict, data: dict) -> int:
    """Create or refresh the DRAFT order row backing this wizard run."""
    Session = session_factory(engine)
    with Session() as session:
        order = (
            order_service.get_order(session, st.session_state.wizard_order_id)
            if st.session_state.get("wizard_order_id")
            else None
        )
        kwargs = dict(
            department=data.get("department", ""),
            category=data["category"],
            quantity=int(data.get("quantity") or 1),
            budget_minor=data["budget_minor"],
            deadline=data["deadline"],
            requirements={
                "category": data["category"],
                "attributes": data.get("attributes", {}),
                "warranty_months_min": data.get("warranty_months_min"),
            },
            preferences={},
        )
        if order is not None:
            order_service.update_draft_order(session, order, **kwargs)
            order_id = order.id
        else:
            order = order_service.create_order(
                session, requester_id=user["id"], source="wizard", **kwargs
            )
            order_id = order.id
            st.session_state.wizard_order_id = order_id
    return order_id


def render(engine, user: dict) -> None:
    st.title("New Order Request")
    st.caption("One step at a time — no forms to fill in one go.")

    st.session_state.setdefault("wizard_step", 0)
    st.session_state.setdefault("wizard", {})
    st.session_state.setdefault("wizard_order_id", None)
    data = st.session_state.wizard

    # ---- resumable drafts --------------------------------------------------
    Session = session_factory(engine)
    with Session() as session:
        drafts = order_service.user_drafts(session, user["id"])
    if drafts and st.session_state.wizard_step == 0 and not data:
        with st.expander(f"Resume a draft ({len(drafts)})", expanded=bool(drafts)):
            for d in drafts:
                col1, col2, col3 = st.columns([3, 1, 1])
                col1.markdown(
                    f"{d.order_no} — {d.category or '—'} × {d.quantity or '?'} "
                    f"{status_badge(d.status)}",
                    unsafe_allow_html=True,
                )
                if col2.button("Continue", key=f"resume_{d.id}"):
                    Session2 = session_factory(engine)
                    with Session2() as s2:
                        order = order_service.get_order(s2, d.id)
                        reqs = json.loads(order.requirements_json or "{}")
                        st.session_state.wizard = {
                            "category": order.category,
                            "attributes": reqs.get("attributes", {}),
                            "warranty_months_min": reqs.get("warranty_months_min"),
                            "quantity": order.quantity,
                            "budget_minor": order.budget_minor,
                            "deadline": order.deadline,
                            "department": order.department,
                        }
                        st.session_state.wizard_order_id = order.id
                        st.session_state.wizard_step = 1
                    st.rerun()
                if col3.button("Discard", key=f"discard_{d.id}"):
                    Session2 = session_factory(engine)
                    with Session2() as s2:
                        order_service.discard_draft(s2, order_service.get_order(s2, d.id))
                    st.rerun()

    # ---- progress bar -------------------------------------------------------
    step = st.session_state.wizard_step
    st.progress((step) / len(STEPS))
    st.markdown(f"**Step {step + 1} of {len(STEPS)} — {STEPS[step]}**")

    # ---- step content -------------------------------------------------------
    if step == 0:
        options = [
            f"{spec.label} — {', '.join(a.display_name for a in spec.attributes)}"
            for spec in CATEGORIES.values()
        ] + ["Other — I'll describe it myself"]
        picked = st.radio("What do you need?", options, key="wizard_category_pick")
        if picked == options[-1]:
            data["category"] = OTHER_CATEGORY
            st.info(
                "The agent will search live supplier sites with your "
                "description and match products against your keywords."
            )
        else:
            data["category"] = list(CATEGORIES)[options.index(picked)]
            st.info(
                "The agent can source these categories. Anything else is out of "
                "scope for this demo."
            )

    elif step == 1:
        category = data.get("category")
        if category is None:
            st.warning("Pick a category first.")
            if st.button("Back"):
                st.session_state.wizard_step = 0
                st.rerun()
            st.stop()
        if category == OTHER_CATEGORY:
            item = st.text_input(
                "What do you need?",
                value=data.get("attributes", {}).get("item", "") or "",
                help="A short product description, e.g. 'noise cancelling headphones'.",
                key="wizard_field_item",
            )
            keywords_csv = st.text_input(
                "Required keywords (comma-separated)",
                value=", ".join(data.get("attributes", {}).get("keywords", []) or []),
                help=(
                    "Matched against each product's specifications — e.g. "
                    "'noise cancelling, bluetooth'. Every keyword must appear."
                ),
                key="wizard_field_keywords",
            )
            data["attributes"] = {
                "item": item.strip(),
                "keywords": [k.strip() for k in keywords_csv.split(",") if k.strip()],
            }
            data["warranty_months_min"] = st.number_input(
                "Minimum warranty (months, 0 = any)",
                min_value=0,
                value=int(data.get("warranty_months_min") or 0),
                key="wizard_field_warranty",
            )
        else:
            spec = CATEGORIES[category]
            st.markdown(f"**{spec.label}** — tell me the mandatory specs:")
            for attr in spec.attributes:
                _attribute_widget(attr, attr.name)
            data["attributes"] = _capture_attribute_values(category)
            data["warranty_months_min"] = st.number_input(
                "Minimum warranty (months, 0 = any)",
                min_value=0,
                value=int(data.get("warranty_months_min") or 0),
                key="wizard_field_warranty",
            )

    elif step == 2:
        data["quantity"] = st.number_input(
            "How many units?",
            min_value=1,
            value=int(data.get("quantity") or 1),
            key="wizard_field_quantity",
        )
        budget_major = st.number_input(
            "Maximum total budget (HKD)",
            min_value=0.0,
            value=float(data.get("budget_minor", 0)) / 100 or 0.0,
            step=100.0,
            key="wizard_field_budget",
        )
        data["budget_minor"] = int(round(budget_major * 100))
        default_date = data.get("deadline") or date.today() + timedelta(days=14)
        picked_date = st.date_input(
            "Needed by", value=default_date, key="wizard_field_deadline"
        )
        data["deadline"] = picked_date if isinstance(picked_date, date) else default_date
        data["department"] = (
            st.text_input(
                "Department",
                value=data.get("department", "") or "",
                key="wizard_field_department",
            )
            or ""
        )

    elif step == 3:
        order_id = _save_autosave(engine, user, data)
        Session = session_factory(engine)
        with Session() as session:
            order = order_service.get_order(session, order_id)
            st.markdown(
                f"**{order.order_no}** — {status_badge(order.status)}",
                unsafe_allow_html=True,
            )
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Requested**")
            st.markdown(
                pretty_requirements(
                    json.dumps(
                        {
                            "category": data.get("category"),
                            "attributes": data.get("attributes") or {},
                            "warranty_months_min": data.get("warranty_months_min") or None,
                        }
                    )
                )
            )
            st.markdown(
                f"- **Quantity:** {data.get('quantity')}\n"
                f"- **Budget (max):** HK${(data.get('budget_minor') or 0) / 100:,.2f}\n"
                f"- **Deadline:** {data.get('deadline')}\n"
                f"- **Department:** {data.get('department') or '—'}"
            )
        st.info(
            "On submit, the agent browses every approved supplier site, extracts "
            "and verifies offers, and queues the best compliant one for manager "
            "approval."
        )
        if st.button("Submit order request", type="primary", use_container_width=True):
            Session = session_factory(engine)
            with Session() as session:
                order = order_service.get_order(session, order_id)
                if not data.get("department"):
                    st.error("Department is required before submitting.")
                    st.stop()
                order_service.submit_order(session, order)
                start_research_thread(engine, order.id)
                st.success(f"{order.order_no} submitted — the agent is on it.")
            _reset_wizard()
            st.rerun()
        if st.button("Keep editing"):
            st.session_state.wizard_step = 2
            st.rerun()

    # ---- navigation ---------------------------------------------------------
    if step < 3:
        col1, _ = st.columns([1, 3])
        if col1.button("Next →", type="primary", disabled=(step == 2 and not data.get("department"))):
            if step == 1:
                if data.get("category") == OTHER_CATEGORY:
                    attrs = data.get("attributes") or {}
                    if not attrs.get("item"):
                        st.error("Please describe what you need.")
                        st.stop()
                    if not attrs.get("keywords"):
                        st.error(
                            "Please add at least one required keyword — offers are "
                            "matched against them."
                        )
                        st.stop()
                else:
                    spec = CATEGORIES[data["category"]]
                    missing = [
                        a.display_name
                        for a in spec.attributes
                        if a.required and not data.get("attributes", {}).get(a.name)
                    ]
                    if missing:
                        st.error(f"Please fill in: {', '.join(missing)}")
                        st.stop()
            st.session_state.wizard_step += 1
            if st.session_state.wizard_step == 3:
                _save_autosave(engine, user, data)
            st.rerun()
    if step > 0:
        if st.button("← Back"):
            st.session_state.wizard_step -= 1
            st.rerun()
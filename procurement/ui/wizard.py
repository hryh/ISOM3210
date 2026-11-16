"""Page 1 — Order Request: a single-screen request builder.

Type what you need in your own words. The request is matched onto the typed
catalog when it can be (deterministic detection — the specs you state become
checks; the rest are *no preference* and never enforced) and routes to the
live keyword-search flow when it can't, so nothing is constrained to a fixed
category list. A DRAFT order row autosaves behind the screen so a
half-finished request survives a refresh.
"""

from __future__ import annotations

import json
from datetime import date

import streamlit as st

from .. import order_service
from ..catalog import BOOL, CATEGORIES, INT, LIST, OTHER_CATEGORY, detect_category
from ..repository import session_factory
from ..research import start_research_thread
from .common import pretty_requirements, render_order_status, status_badge

NO_PREFERENCE = "No preference"
AUTO_DETECT = "Auto-detect"
KEYWORD_SEARCH = "Something else (keyword search)"


def _reset_wizard() -> None:
    st.session_state.wizard = {}
    st.session_state.wizard_order_id = None


# ---------------------------------------------------------------------------
# Spec widgets — every spec has an explicit "No preference" state
# ---------------------------------------------------------------------------

def _attribute_widget(attr, current):
    """One catalog attribute as a widget with a visible no-preference state.

    ``None`` is stored for no preference — the same representation the rules
    engine already treats as "not requested, not enforced".
    """
    key = f"wizard_field_{attr.name}"
    if attr.choices is not None:
        if attr.type == LIST:
            picked = st.multiselect(
                f"{attr.display_name} (choose all you require)",
                list(attr.choices),
                default=current or [],
                key=key,
                help="Leave empty for no preference.",
            )
            return picked or None
        options = [NO_PREFERENCE, *attr.choices]
        default = current if current in options else NO_PREFERENCE
        picked = st.selectbox(
            attr.display_name, options, index=options.index(default), key=key
        )
        return None if picked == NO_PREFERENCE else picked
    if attr.type == INT:
        on = st.toggle(
            f"Set a minimum {attr.display_name}",
            value=current is not None,
            key=f"{key}_on",
        )
        if not on:
            return None
        return st.number_input(
            attr.display_name, min_value=0, value=int(current or 0), key=key
        )
    if attr.type == BOOL:
        options = [NO_PREFERENCE, "Yes", "No"]
        default = {None: NO_PREFERENCE, True: "Yes", False: "No"}[current]
        picked = st.radio(
            attr.display_name,
            options,
            horizontal=True,
            index=options.index(default),
            key=key,
        )
        return {NO_PREFERENCE: None, "Yes": True, "No": False}[picked]
    return st.text_input(attr.display_name, value=current or "", key=key) or None


def _warranty_widget(current):
    """Minimum warranty — a toggle replaces the old '0 means any' hack."""
    on = st.toggle(
        "Require a minimum warranty",
        value=current is not None,
        key="wizard_field_warranty_on",
    )
    if not on:
        return None
    return st.number_input(
        "Minimum warranty (months)",
        min_value=0,
        value=int(current or 12),
        key="wizard_field_warranty",
    )


# ---------------------------------------------------------------------------
# Category resolution
# ---------------------------------------------------------------------------

def _resolve_category(data: dict) -> str:
    """Explicit override wins; otherwise detect from the item text.

    Detection never blocks: an unmatched item routes to the keyword-search
    flow, which works for anything the agent can find on a supplier site.
    """
    override = data.get("category_override")
    if override in CATEGORIES:
        return override
    if override == OTHER_CATEGORY:
        return OTHER_CATEGORY
    return detect_category(data.get("item_text")) or OTHER_CATEGORY


# ---------------------------------------------------------------------------
# Draft persistence
# ---------------------------------------------------------------------------

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
            department=data.get("department") or "",
            category=data["category"],
            quantity=int(data.get("quantity") or 1),
            budget_minor=int(data.get("budget_minor") or 0),
            deadline=data.get("deadline"),
            requirements={
                "category": data["category"],
                "attributes": data.get("attributes") or {},
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


def _widget_state_for(name: str, value, category: str):
    """Translate a stored attribute value into its widget's state value."""
    spec = CATEGORIES.get(category)
    attr = spec.attribute_map.get(name) if spec else None
    if attr is None:
        return value
    if attr.choices is not None:
        if attr.type == LIST:
            return value or []
        return value if value in attr.choices else NO_PREFERENCE
    if attr.type == BOOL:
        return {None: NO_PREFERENCE, True: "Yes", False: "No"}[value]
    return value


def _seed_widget_state(data: dict) -> None:
    """Seed widget states from a resumed draft (Streamlit-sanctioned way)."""
    st.session_state["wizard_item_text"] = data.get("item_text") or ""
    st.session_state["wizard_field_department"] = data.get("department") or ""
    st.session_state["wizard_field_quantity"] = int(data.get("quantity") or 1)
    st.session_state["wizard_field_budget"] = float(data.get("budget_minor") or 0) / 100
    if data.get("deadline"):
        st.session_state["wizard_field_deadline"] = data["deadline"]

    category = data.get("category") or OTHER_CATEGORY
    override = data.get("category_override")
    if override in CATEGORIES:
        st.session_state["wizard_category_override"] = CATEGORIES[override].label
    elif override == OTHER_CATEGORY:
        st.session_state["wizard_category_override"] = KEYWORD_SEARCH

    attrs = data.get("attributes") or {}
    if category == OTHER_CATEGORY:
        st.session_state["wizard_field_item"] = attrs.get("item") or ""
        st.session_state["wizard_field_keywords"] = ", ".join(attrs.get("keywords") or [])
    else:
        for name, value in attrs.items():
            st.session_state[f"wizard_field_{name}"] = _widget_state_for(name, value, category)
            if name in (CATEGORIES.get(category).attribute_map if CATEGORIES.get(category) else {}):
                attr = CATEGORIES[category].attribute_map[name]
                if attr.type == INT:
                    st.session_state[f"wizard_field_{name}_on"] = value is not None
    warranty = data.get("warranty_months_min")
    st.session_state["wizard_field_warranty_on"] = warranty is not None
    if warranty is not None:
        st.session_state["wizard_field_warranty"] = int(warranty)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate(data: dict, category: str) -> list[str]:
    errors: list[str] = []
    if category == OTHER_CATEGORY:
        attrs = data.get("attributes") or {}
        if not attrs.get("item"):
            errors.append("Describe the item you need.")
        if not attrs.get("keywords"):
            errors.append(
                "Add at least one required keyword — offers are matched against them."
            )
    if not (data.get("department") or "").strip():
        errors.append("Department is required before submitting.")
    return errors


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

def render(engine, user: dict) -> None:
    st.title("New Order Request")
    st.caption(
        "Describe it in your own words — the agent checks supplier sites "
        "against whatever you actually require."
    )

    st.session_state.setdefault("wizard", {})
    st.session_state.setdefault("wizard_order_id", None)

    # ---- just-submitted order: keep the live run console on screen ----------
    submitted_id = st.session_state.get("wizard_submitted_order")
    if submitted_id is not None:
        Session = session_factory(engine)
        with Session() as session:
            submitted = order_service.get_order(session, submitted_id)
        if submitted is None or submitted.status == order_service.OrderStatus.DRAFT.value:
            st.session_state.pop("wizard_submitted_order", None)
        else:
            st.title("Order request submitted")
            st.caption(
                "The agent browses every approved supplier site, verifies each "
                "offer against the rules, and queues the best one for approval."
            )
            render_order_status(engine, submitted_id)
            if st.button("Start another request"):
                st.session_state.pop("wizard_submitted_order", None)
                st.rerun()
            return

    data = st.session_state.wizard

    # ---- resumable drafts -----------------------------------------------------
    Session = session_factory(engine)
    with Session() as session:
        drafts = order_service.user_drafts(session, user["id"])
    if drafts and not data:
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
                        attrs = reqs.get("attributes", {})
                        spec = CATEGORIES.get(order.category)
                        st.session_state.wizard = {
                            "item_text": (
                                attrs.get("item") or ""
                                if order.category == OTHER_CATEGORY
                                else (spec.label if spec else "")
                            ),
                            "category": order.category,
                            "category_override": order.category,
                            "attributes": attrs,
                            "warranty_months_min": reqs.get("warranty_months_min"),
                            "quantity": order.quantity,
                            "budget_minor": order.budget_minor,
                            "deadline": order.deadline,
                            "department": order.department,
                        }
                        st.session_state.wizard_order_id = order.id
                        _seed_widget_state(st.session_state.wizard)
                    st.rerun()
                if col3.button("Discard", key=f"discard_{d.id}"):
                    Session2 = session_factory(engine)
                    with Session2() as s2:
                        order_service.discard_draft(s2, order_service.get_order(s2, d.id))
                    st.rerun()

    # ---- what do you need -------------------------------------------------
    item_text = st.text_input(
        "What do you need?",
        value=data.get("item_text") or "",
        key="wizard_item_text",
        placeholder="e.g. 2 office chairs with lumbar support — or anything else",
    )
    data["item_text"] = item_text

    category = _resolve_category(data)
    if data.get("category") != category:
        data["category"] = category
        data["attributes"] = {}  # fresh spec set per category

    if category != OTHER_CATEGORY:
        spec = CATEGORIES[category]
        st.success(
            f"Recognised as **{spec.label}** — offers will be checked against "
            "the specs you set below. Anything left as *No preference* "
            "won't be enforced."
        )
    else:
        st.info(
            "I couldn't match this to a known product type, so I'll search "
            "live supplier sites for it and match offers against keywords "
            "you require."
        )
    with st.expander("Not right? Pick a category"):
        options = [AUTO_DETECT, KEYWORD_SEARCH, *(s.label for s in CATEGORIES.values())]
        picked = st.selectbox("Category", options, key="wizard_category_override")
        mapping = {AUTO_DETECT: None, KEYWORD_SEARCH: OTHER_CATEGORY}
        mapping.update({s.label: cid for cid, s in CATEGORIES.items()})
        data["category_override"] = mapping[picked]

    # ---- specifications (all optional) ------------------------------------
    st.subheader("Specifications")
    st.caption("All optional — leave anything you don't care about as *No preference*.")
    if category == OTHER_CATEGORY:
        item = st.text_input(
            "Item description",
            value=(data.get("attributes") or {}).get("item") or item_text,
            key="wizard_field_item",
            help="A short product description, e.g. 'noise cancelling headphones'.",
        )
        keywords_csv = st.text_input(
            "Required keywords (comma-separated)",
            value=", ".join((data.get("attributes") or {}).get("keywords", []) or []),
            key="wizard_field_keywords",
            help=(
                "Matched against each product's specifications — e.g. "
                "'noise cancelling, bluetooth'. Every keyword must appear."
            ),
        )
        data["attributes"] = {
            "item": item.strip(),
            "keywords": [k.strip() for k in keywords_csv.split(",") if k.strip()],
        }
    else:
        spec = CATEGORIES[category]
        attributes = {}
        for attr in spec.attributes:
            attributes[attr.name] = _attribute_widget(
                attr, data.get("attributes", {}).get(attr.name)
            )
        data["attributes"] = attributes
    data["warranty_months_min"] = _warranty_widget(data.get("warranty_months_min"))

    # ---- commercial terms ---------------------------------------------------
    st.subheader("Commercial terms")
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
    # Needed-by is optional — it can be set later when the supplier is
    # contacted. An empty picker stores None.
    picked_date = st.date_input(
        "Needed by (optional)",
        value=data.get("deadline"),
        key="wizard_field_deadline",
        help="Leave empty to decide later, when contacting the supplier.",
    )
    data["deadline"] = picked_date if isinstance(picked_date, date) else None
    data["department"] = (
        st.text_input(
            "Department",
            value=data.get("department", "") or "",
            key="wizard_field_department",
        )
        or ""
    )

    # ---- live review + submit ------------------------------------------------
    if not item_text:
        st.caption("Type what you need above — a live summary builds below.")
        return

    st.subheader("Review")
    with st.container(border=True):
        order_id = _save_autosave(engine, user, data)
        Session = session_factory(engine)
        with Session() as session:
            order = order_service.get_order(session, order_id)
            st.markdown(
                f"**{order.order_no}** — {status_badge(order.status)}",
                unsafe_allow_html=True,
            )
        requirements = {
            "category": category,
            "attributes": data.get("attributes") or {},
            "warranty_months_min": data.get("warranty_months_min"),
        }
        st.markdown(pretty_requirements(json.dumps(requirements)))
        st.markdown(
            f"- **Quantity:** {data.get('quantity')}\n"
            f"- **Budget (max):** HK${(data.get('budget_minor') or 0) / 100:,.2f}\n"
            f"- **Needed by:** {data.get('deadline') or '— (decide later)'}\n"
            f"- **Department:** {data.get('department') or '—'}"
        )
        if category != OTHER_CATEGORY:
            spec = CATEGORIES[category]
            unset = sum(1 for a in spec.attributes if not data.get("attributes", {}).get(a.name))
            if unset:
                st.caption(
                    f"{unset} spec"
                    f"{'s' if unset != 1 else ''} left as no preference — "
                    "they won't be enforced against offers."
                )
        st.caption(
            "On submit, the agent browses every approved supplier site, "
            "extracts and verifies offers, and queues the best compliant one "
            "for approval."
        )

    if st.button("Submit order request", type="primary", use_container_width=True):
        errors = _validate(data, category)
        if errors:
            st.error(" ".join(errors))
            st.stop()
        Session = session_factory(engine)
        with Session() as session:
            order = order_service.get_order(session, order_id)
            order_service.submit_order(session, order)
            start_research_thread(engine, order.id)
            st.session_state.wizard_submitted_order = order.id
        _reset_wizard()
        st.rerun()
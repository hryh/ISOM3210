"""Research orchestrator — the blackbox boundary.

Given a submitted order, this module drives the agent: for every approved
supplier, browse and extract products, persist them as ``products`` rows, then
run the deterministic rules engine to select the best compliant offer. The
order ends up ``PENDING_APPROVAL`` (with a selected product) or ``NO_OFFER``.

Nothing about the research process is stored — only its outputs (products,
selected product, order status). Designed to run inside a background thread
via :func:`start_research_thread`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from datetime import datetime, timezone

from sqlalchemy import select

from . import order_service
from .repository import Product, Supplier, User, session_factory, upsert_product
from .schemas import OfferEvidence, PurchaseRequest, RequestRequirements
from .tools.suppliers import compare_offers, research_supplier, validate_offer

logger = logging.getLogger(__name__)


def _order_to_request(order, requester: User) -> PurchaseRequest:
    """Rebuild the typed request the rules engine expects from an order row."""
    requirements = json.loads(order.requirements_json or "{}")
    return PurchaseRequest(
        request_id=order.order_no,
        requester=requester.display_name,
        department=order.department,
        category=order.category,
        quantity=order.quantity,
        max_total_cost_minor=order.budget_minor,
        deadline=order.deadline,
        mandatory=RequestRequirements(
            category=requirements.get("category", order.category),
            attributes=requirements.get("attributes", {}),
            warranty_months_min=requirements.get("warranty_months_min"),
        ),
        preferences=json.loads(order.preferences_json or "{}"),
        created_at=order.created_at,
    )


def _evidence_delivery_days(evidence: OfferEvidence) -> int | None:
    if evidence.delivery_by is None:
        return None
    return (evidence.delivery_by - datetime.now(timezone.utc).date()).days


def _persist_evidence(session, supplier: Supplier, evidence: OfferEvidence) -> None:
    upsert_product(
        session,
        supplier_id=supplier.id,
        product_key=evidence.product_id,
        category=evidence.category,
        model_name=evidence.model_name,
        attributes=evidence.attributes,
        unit_price_minor=evidence.unit_price_minor,
        shipping_minor=evidence.shipping_minor,
        available_quantity=evidence.available_quantity,
        warranty_months=evidence.warranty_months,
        delivery_days=_evidence_delivery_days(evidence),
        retrieved_at=evidence.retrieved_at,
    )


async def _research(engine, order_id: int) -> None:
    Session = session_factory(engine)
    with Session() as session:
        order = order_service.get_order(session, order_id)
        if order is None or order.status != order_service.OrderStatus.RESEARCHING.value:
            return

        requester = session.get(User, order.requester_id)
        request = _order_to_request(order, requester)
        suppliers = list(
            session.scalars(
                select(Supplier).where(Supplier.status == "approved")
            )
        )

        offers: list[OfferEvidence] = []
        for supplier in suppliers:
            try:
                evidences = await research_supplier(request, supplier)
            except Exception as exc:  # a broken site must not kill the run
                logger.warning("research failed for %s: %s", supplier.name, exc)
                continue
            for evidence in evidences:
                _persist_evidence(session, supplier, evidence)
                offers.append(evidence)

        results = [validate_offer(request, offer) for offer in offers]
        comparison = compare_offers(request, offers, results)

        session.expire_all()
        order = order_service.get_order(session, order_id)
        if comparison.selected_offer_id is None:
            order_service.transition(session, order, order_service.OrderStatus.NO_OFFER)
            return

        # Map the selected offer back to its product row.
        selected_supplier_id, _, selected_key = comparison.selected_offer_id.rpartition(":")
        product = (
            session.query(Product)
            .join(Supplier, Product.supplier_id == Supplier.id)
            .filter(
                Supplier.id == int(selected_supplier_id),
                Product.product_key == selected_key,
            )
            .one_or_none()
        )
        if product is None:  # pragma: no cover - defensive
            order_service.transition(session, order, order_service.OrderStatus.NO_OFFER)
            return

        order.selected_product_id = product.id
        session.commit()
        order_service.transition(
            session, order, order_service.OrderStatus.PENDING_APPROVAL
        )


def run_research(engine, order_id: int) -> None:
    """Synchronous entry point (for a background thread)."""
    try:
        asyncio.run(_research(engine, order_id))
    except Exception:
        logger.exception("research for order %s crashed", order_id)
        # No compliant outcome is provable when the run itself failed.
        Session = session_factory(engine)
        with Session() as session:
            order = order_service.get_order(session, order_id)
            if order and order.status == order_service.OrderStatus.RESEARCHING.value:
                try:
                    order_service.transition(
                        session, order, order_service.OrderStatus.NO_OFFER
                    )
                except order_service.TransitionError:  # pragma: no cover
                    pass


def start_research_thread(engine, order_id: int) -> threading.Thread:
    """Spawn the blackbox research run for an order (fire-and-forget)."""
    thread = threading.Thread(
        target=run_research,
        args=(engine, order_id),
        name=f"research-order-{order_id}",
        daemon=True,
    )
    thread.start()
    return thread
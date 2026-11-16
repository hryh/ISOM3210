"""Print the contents of the human-record tables.

Usage:
    uv run python scripts/inspect_db.py
"""

from __future__ import annotations

from procurement.repository import (
    ChatMessage,
    ChatSession,
    Order,
    OrderDecision,
    Product,
    Supplier,
    User,
    create_engine_from_url,
    init_db,
    session_factory,
)


def main() -> None:
    engine = create_engine_from_url()
    init_db(engine)
    Session = session_factory(engine)

    with Session() as session:
        print("=== users ===")
        for u in session.query(User).all():
            print(
                f"  {u.id:>4} {u.username:16s} role={u.role:8s} "
                f"active={u.active}"
            )

        print("=== suppliers ===")
        for s in session.query(Supplier).all():
            print(
                f"  {s.id:>4} {s.name:24s} status={s.status:8s} origin={s.origin}"
            )

        print("=== products ===")
        for p in session.query(Product).all():
            print(
                f"  {p.id:>4} supplier={p.supplier_id} key={p.product_key:20s} "
                f"price={p.unit_price_minor} qty={p.available_quantity}"
            )

        print("=== orders ===")
        for o in session.query(Order).all():
            print(
                f"  {o.order_no} status={o.status:16s} requester={o.requester_id} "
                f"product={o.selected_product_id} created={o.created_at}"
            )

        print("=== order_decisions ===")
        for d in session.query(OrderDecision).all():
            print(
                f"  order={d.order_id} {d.decision:8s} by={d.decided_by} "
                f"({d.role}) at={d.decided_at} reason={d.reason!r}"
            )

        print("=== chat_sessions ===")
        for c in session.query(ChatSession).all():
            print(
                f"  {c.id:>4} {c.title:32s} user={c.user_id} order={c.order_id}"
            )

        print("=== chat_messages ===")
        for m in session.query(ChatMessage).all():
            print(f"  session={m.session_id} {m.role:9s} {m.content[:60]!r}")


if __name__ == "__main__":
    main()
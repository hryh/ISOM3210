from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from procurement.repository import (
    Supplier,
    init_db,
    session_factory,
    upsert_product,
)


def _memory_engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _now():
    return datetime.now(timezone.utc)


def test_upsert_product_creates_row():
    engine = _memory_engine()
    init_db(engine)
    Session = session_factory(engine)

    with Session() as session:
        supplier = Supplier(
            name="Pixel Peak Supplies",
            origin="http://127.0.0.1:8100",
            status="approved",
            created_at=_now(),
        )
        session.add(supplier)
        session.flush()

        product = upsert_product(
            session,
            supplier_id=supplier.id,
            product_key="SUP_A_MON_001",
            category="monitor",
            model_name="Vision 27",
            unit_price_minor=330033,
            available_quantity=5,
            retrieved_at=_now(),
        )

        assert product.id is not None
        assert product.unit_price_minor == 330033
        assert product.available_quantity == 5
        # Unknown facts stay None — never zero or invented defaults.
        assert product.shipping_minor is None
        assert product.delivery_days is None


def test_upsert_product_refreshes_known_and_preserves_unknown():
    engine = _memory_engine()
    init_db(engine)
    Session = session_factory(engine)

    with Session() as session:
        supplier = Supplier(
            name="Beacon Bay Office Co.",
            origin="http://127.0.0.1:8100",
            status="approved",
            created_at=_now(),
        )
        session.add(supplier)
        session.flush()

        first = upsert_product(
            session,
            supplier_id=supplier.id,
            product_key="SUP_B_KEY_006",
            category="keyboard",
            unit_price_minor=150000,
            retrieved_at=_now(),
        )

        # Second scrape only knows quantity; the known price must survive.
        second = upsert_product(
            session,
            supplier_id=supplier.id,
            product_key="SUP_B_KEY_006",
            category="keyboard",
            available_quantity=9,
            retrieved_at=_now(),
        )

        assert second.id == first.id
        assert second.unit_price_minor == 150000
        assert second.available_quantity == 9


def test_suppliers_unique_names():
    from sqlalchemy.exc import IntegrityError

    engine = _memory_engine()
    init_db(engine)
    Session = session_factory(engine)

    with Session() as session:
        session.add(
            Supplier(name="dup", origin="http://x", status="approved", created_at=_now())
        )
        session.commit()
        session.add(
            Supplier(name="dup", origin="http://y", status="approved", created_at=_now())
        )
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
        else:
            raise AssertionError("duplicate supplier name was allowed")


def test_ensure_columns_migrates_existing_suppliers_table():
    """Regression: a DB created before catalog_url existed must not crash."""
    from sqlalchemy import text

    from procurement.repository import _ensure_columns, create_engine_from_url

    engine = create_engine_from_url("sqlite://")
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql(
            "CREATE TABLE suppliers (id INTEGER PRIMARY KEY, name VARCHAR, "
            "origin VARCHAR, status VARCHAR)"
        )
        conn.exec_driver_sql("INSERT INTO suppliers (name, origin, status) "
                             "VALUES ('old', 'http://x', 'approved')")

    _ensure_columns(engine)

    rows = engine.connect().execute(text("SELECT * FROM suppliers")).fetchall()
    assert rows and rows[0][1] == "old"
    columns = {r[1] for r in engine.connect().execute(text("PRAGMA table_info(suppliers)"))}
    assert "catalog_url" in columns
    # Idempotent: running again must not fail or duplicate the column.
    _ensure_columns(engine)


def test_reset_db_handles_stale_old_schema():
    """Regression: old agent-centric tables (offers -> suppliers FK) must not
    block the drop, even with PRAGMA foreign_keys=ON on every connection."""
    from sqlalchemy import text

    from procurement.repository import _is_stale_schema, create_engine_from_url

    engine = create_engine_from_url("sqlite://")  # FK pragma listener attached
    # Fabricate the old schema: offers references suppliers.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        conn.exec_driver_sql("CREATE TABLE suppliers (id VARCHAR PRIMARY KEY, name VARCHAR)")
        conn.exec_driver_sql(
            "CREATE TABLE offers (id VARCHAR PRIMARY KEY, "
            "supplier_id VARCHAR REFERENCES suppliers (id))"
        )
        conn.exec_driver_sql(
            "CREATE TABLE requests (id VARCHAR PRIMARY KEY, requester VARCHAR)"
        )

    assert _is_stale_schema(engine) is True

    from procurement.repository import reset_db

    reset_db(engine)  # previously raised FOREIGN KEY constraint failed

    tables = set(
        engine.connect().execute(text("SELECT name FROM sqlite_master WHERE type='table'")).scalars()
    )
    assert "offers" not in tables
    assert "requests" not in tables
    assert {"users", "suppliers", "products", "orders"} <= tables
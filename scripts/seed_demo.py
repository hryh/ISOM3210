"""Reset the SQLite database and seed core demo data.

Usage: ``uv run python scripts/seed_demo.py``

Drops everything (demo data is disposable), then seeds the admin manager user
and the three mock suppliers the agent browses.
"""

from __future__ import annotations

from procurement.repository import create_engine_from_url, reset_db, session_factory
from procurement.seed import seed_core


def main() -> None:
    engine = create_engine_from_url()
    reset_db(engine)

    Session = session_factory(engine)
    with Session() as session:
        seeded = seed_core(session)

    print(
        f"Seeded admin user (id={seeded['admin']}) and "
        f"{seeded['suppliers']} suppliers."
    )
    print("Demo login: admin / admin123 (override with DEMO_ADMIN_PASSWORD).")


if __name__ == "__main__":
    main()
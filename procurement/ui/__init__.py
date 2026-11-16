"""Streamlit UI package — page renderers imported by the app.py router.

Each module exposes a ``render(engine, user)`` function. ``user`` is the
session-state snapshot dict: ``{"id", "username", "display_name", "role"}``.
"""

from __future__ import annotations
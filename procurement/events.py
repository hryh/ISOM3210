"""Ephemeral research-run events — the live "what the agent is doing" feed.

The database stays the human record (research outputs only); the run track is
a *transient* view into the blackbox while it works. Events live in memory,
die with the process, and the UI degrades gracefully to outputs-only after a
restart — losing a progress animation is fine, losing a decision is not.

Thread-safe by design: research runs inside a background thread while the
Streamlit UI polls from the main thread.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

#: Event kinds the UI understands. ``visit`` carries the browser URL so the
#: viewer can show what the agent is reading; the rest are log lines.
RUN_STARTED = "run_started"
VISIT = "visit"
SUPPLIER_DONE = "supplier_done"
SUPPLIER_FAILED = "supplier_failed"
EVALUATING = "evaluating"
CHECKED = "checked"
SELECTED = "selected"
NO_OFFER = "no_offer"
CRASHED = "crashed"

#: Memory fences: never grow without bound in a long-lived process.
MAX_TRACKED_ORDERS = 32
MAX_EVENTS_PER_ORDER = 200


@dataclass(frozen=True)
class RunEvent:
    """One observable step of a research run."""

    order_id: int
    kind: str
    message: str
    ts: datetime
    #: Free-form context (e.g. ``url`` for visits, ``supplier_id`` for logs).
    detail: dict = field(default_factory=dict)


_lock = threading.Lock()
_events: dict[int, list[RunEvent]] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def emit(order_id: int, kind: str, message: str, **detail) -> None:
    """Append one event to an order's run track (thread-safe, never raises).

    Memory fences only: the store is a UI nicety, so a full or evicted track
    is truncated, never an error.
    """
    event = RunEvent(order_id=order_id, kind=kind, message=message, ts=_now(), detail=detail)
    with _lock:
        track = _events.setdefault(order_id, [])
        track.append(event)
        if len(track) > MAX_EVENTS_PER_ORDER:
            del track[: len(track) - MAX_EVENTS_PER_ORDER]
        if len(_events) > MAX_TRACKED_ORDERS:
            # Evict the order whose newest event is oldest (simple LRU-ish).
            oldest = min(_events, key=lambda oid: _events[oid][-1].ts)
            if oldest != order_id:
                del _events[oldest]


def events(order_id: int) -> list[RunEvent]:
    """A snapshot of the order's run track (oldest first)."""
    with _lock:
        return list(_events.get(order_id, []))


def last(order_id: int) -> RunEvent | None:
    """The most recent event, or ``None`` when the track is empty."""
    with _lock:
        track = _events.get(order_id)
        return track[-1] if track else None


def clear(order_id: int) -> None:
    """Forget an order's track (e.g. when its draft is discarded)."""
    with _lock:
        _events.pop(order_id, None)
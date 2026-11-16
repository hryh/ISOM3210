"""Unit tests for the ephemeral run-event store."""

from __future__ import annotations

import threading

from procurement import events


def test_emit_and_read_back():
    events.clear(1)
    events.emit(1, events.RUN_STARTED, "start")
    events.emit(1, events.VISIT, "Reading Pixel Peak…", url="http://127.0.0.1:8100")

    track = events.events(1)
    assert [e.kind for e in track] == [events.RUN_STARTED, events.VISIT]
    assert track[1].detail["url"] == "http://127.0.0.1:8100"
    assert track[1].order_id == 1
    assert events.last(1).kind == events.VISIT


def test_tracks_are_isolated_per_order():
    events.clear(1)
    events.clear(2)
    events.emit(1, events.RUN_STARTED, "a")
    events.emit(2, events.RUN_STARTED, "b")
    assert [e.message for e in events.events(1)] == ["a"]
    assert [e.message for e in events.events(2)] == ["b"]


def test_clear_forgets_a_track():
    events.emit(3, events.RUN_STARTED, "a")
    events.clear(3)
    assert events.events(3) == []
    assert events.last(3) is None


def test_per_order_cap_trims_oldest():
    events.clear(9)
    extra = 50
    for i in range(events.MAX_EVENTS_PER_ORDER + extra):
        events.emit(9, "tick", f"m{i}")
    track = events.events(9)
    assert len(track) == events.MAX_EVENTS_PER_ORDER
    assert track[0].message == f"m{extra}"
    assert track[-1].message == f"m{events.MAX_EVENTS_PER_ORDER + extra - 1}"


def test_emit_is_thread_safe():
    events.clear(5)
    per_thread = 20

    def spam():
        for _ in range(per_thread):
            events.emit(5, "tick", "x")

    threads = [threading.Thread(target=spam) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(events.events(5)) == 8 * per_thread
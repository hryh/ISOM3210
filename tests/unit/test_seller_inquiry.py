"""Chatbot product questions → optional seller inquiry (fake model, fake webhook)."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from procurement import seller_inquiry as si
from procurement.tools import seller_contact as sc

RECEIVED: list[dict] = []


class _Hook(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        RECEIVED.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args):
        pass


@pytest.fixture
def hook(monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), _Hook)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    RECEIVED.clear()
    monkeypatch.setenv(sc.URL_ENV, f"http://127.0.0.1:{server.server_port}/hook")
    monkeypatch.setenv(sc.AUTH_ENV, "Bearer test-token")
    yield
    server.shutdown()


class FakeLLM:
    def __init__(self, answer: dict):
        self.answer = answer
        self.calls = 0

    async def structured(self, prompt, schema, **options):
        self.calls += 1
        return self.answer


@pytest.mark.parametrize("text, expected", [
    ("Does the Vision 27 have USB-C?", True),
    ("what's the difference between IPS and VA panels", True),
    ("Is the chair's armrest adjustable", True),
    ("6 monitors, 27 inch, budget HK$8,000, for engineering", False),
    ("", False),
])
def test_question_prefilter(text, expected):
    assert si.looks_like_question(text) is expected


def test_request_details_skip_the_model():
    llm = FakeLLM({"product_question": True, "product": "x", "reply": "y"})
    assert si.classify("6 monitors, 27 inch, budget HK$8,000", llm=llm) is None
    assert llm.calls == 0


def test_product_question_is_recognised():
    llm = FakeLLM({"product_question": True, "product": "Vision 27",
                   "reply": "Many 27-inch QHD monitors include USB-C; the seller can confirm."})
    pq = si.classify("Does the Vision 27 have USB-C?", llm=llm)
    assert pq is not None and pq.product == "Vision 27" and "seller" in pq.reply


def test_form_question_is_not_a_product_question():
    llm = FakeLLM({"product_question": False, "product": None, "reply": None})
    assert si.classify("What do I put for category?", llm=llm) is None


def test_model_failure_never_breaks_the_chat():
    class Broken:
        async def structured(self, *a, **k):
            raise RuntimeError("network down")
    assert si.classify("Does it have USB-C?", llm=Broken()) is None


def test_default_message_mentions_who_and_what():
    msg = si.default_message("Does it have USB-C?", employee="Alice",
                             department="engineering", product="Vision 27")
    assert "Alice from the engineering team" in msg and "Vision 27" in msg and "USB-C" in msg


def test_send_inquiry_goes_to_the_demo_number(hook, monkeypatch):
    monkeypatch.delenv(si.PHONE_ENV, raising=False)
    res = si.send_inquiry("Does it have USB-C?", employee="Alice", department="engineering",
                          product="Vision 27", chat_ref="chat-1")
    assert res.sent and res.order_id.startswith("INQ-")
    (body,) = RECEIVED
    assert body["event"] == "seller_inquiry"
    assert body["to"] == "+85291465098"
    assert body["message"] == "Does it have USB-C?"
    assert body["from"] == "Alice" and body["product"] == "Vision 27"
    assert body["inquiry_id"] == res.order_id


def test_order_confirmed_event_unchanged(hook):
    res = sc.request_whatsapp_draft("PO-2026-0001")
    assert res.sent and RECEIVED == [{"event": "order_confirmed", "order_id": "PO-2026-0001"}]

"""Seller-contact webhook: payload, auth header, failure modes, contact log.

Uses a local stand-in server; the real routine is never called from tests.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from procurement.tools import seller_contact as sc

RECEIVED: list[dict] = []


class _Hook(BaseHTTPRequestHandler):
    status = 200
    delay = 0.0

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        RECEIVED.append({"auth": self.headers.get("Authorization"), "body": body})
        time.sleep(type(self).delay)
        self.send_response(type(self).status)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args):
        pass


@pytest.fixture
def hook(monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), _Hook)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    RECEIVED.clear()
    _Hook.status, _Hook.delay = 200, 0.0
    monkeypatch.setenv(sc.URL_ENV, f"http://127.0.0.1:{server.server_port}/hook")
    monkeypatch.setenv(sc.AUTH_ENV, "Authorization: Bearer test-token")
    yield _Hook
    server.shutdown()


def test_sends_event_and_order_number_only(hook):
    res = sc.request_whatsapp_draft("PO-2026-0001")
    assert res.sent and res.status == "sent"
    assert RECEIVED == [{"auth": "Bearer test-token",
                         "body": {"event": "order_confirmed", "order_id": "PO-2026-0001"}}]


def test_http_error_is_a_safe_retry(hook):
    hook.status = 500
    res = sc.request_whatsapp_draft("PO-2026-0002")
    assert not res.sent and res.status == "failed"


def test_timeout_is_uncertain(hook):
    hook.delay = 1.0
    res = sc.request_whatsapp_draft("PO-2026-0003", timeout=0.2)
    assert not res.sent and res.status == "uncertain"


def test_not_configured(monkeypatch):
    monkeypatch.delenv(sc.URL_ENV, raising=False)
    monkeypatch.delenv(sc.AUTH_ENV, raising=False)
    assert not sc.contact_configured()
    assert sc.request_whatsapp_draft("PO-1").status == "not_configured"


def test_contact_log_keeps_latest_attempt_per_order(tmp_path):
    log = tmp_path / "contacts.jsonl"
    assert sc.latest_contacts(log) == {}
    sc.record_contact(sc.ContactResult("PO-1", False, "failed", "HTTP 500"), manager="Mia", path=log)
    sc.record_contact(sc.ContactResult("PO-1", True, "sent", "HTTP 200"), manager="Mia", path=log)
    sc.record_contact(sc.ContactResult("PO-2", False, "uncertain", "timeout"), manager="Ken", path=log)
    latest = sc.latest_contacts(log)
    assert latest["PO-1"]["status"] == "sent" and latest["PO-1"]["manager"] == "Mia"
    assert latest["PO-2"]["status"] == "uncertain"

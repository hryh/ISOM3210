"""Ask the seller-contact routine to draft a WhatsApp message for a confirmed order.

The routine (an external webhook) does NOT message the seller on its own: it asks
the manager for approval before sending anything, and it only receives the event
name and the order id, never the order details.

It is offered only for orders a manager has approved (status PLACED), from the
manager-only Contact Sellers page.
Settings come from the environment (``.env`` locally, Streamlit secrets in the
cloud), never from code or the browser:

    GROK_WEBHOOK_URL            the routine's webhook URL
    GROK_WEBHOOK_AUTHORIZATION  the full Authorization header value, e.g. "Bearer …"
"""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

URL_ENV = "GROK_WEBHOOK_URL"
AUTH_ENV = "GROK_WEBHOOK_AUTHORIZATION"
TIMEOUT_S = 20


@dataclass(frozen=True)
class ContactResult:
    order_id: str
    sent: bool
    #: "sent", "not_configured", "failed" (the routine did not get it: safe to retry)
    #: or "uncertain" (timed out: it may have arrived, so check before retrying).
    status: str
    detail: str = ""


def contact_configured() -> bool:
    return bool(os.environ.get(URL_ENV) and os.environ.get(AUTH_ENV))


def _auth_value(raw: str) -> str:
    """Accept the value with or without a pasted 'Authorization:' label."""
    raw = raw.strip()
    if raw.lower().startswith("authorization:"):
        raw = raw.split(":", 1)[1].strip()
    return raw


def request_whatsapp_draft(order_id: str, *, timeout: float = TIMEOUT_S) -> ContactResult:
    """POST ``{"event": "order_confirmed", "order_id": ...}`` to the routine."""
    order_id = str(order_id)
    url, auth = os.environ.get(URL_ENV, ""), os.environ.get(AUTH_ENV, "")
    if not (url and auth):
        return ContactResult(order_id, False, "not_configured",
                             f"Set {URL_ENV} and {AUTH_ENV} to enable seller contact.")
    req = urllib.request.Request(
        url,
        data=json.dumps({"event": "order_confirmed", "order_id": order_id}).encode(),
        headers={"Authorization": _auth_value(auth), "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return ContactResult(order_id, True, "sent", f"HTTP {resp.status}")
    except urllib.error.HTTPError as exc:
        return ContactResult(order_id, False, "failed", f"The routine answered HTTP {exc.code}.")
    except (TimeoutError, socket.timeout):
        return ContactResult(order_id, False, "uncertain",
                             "No answer within 20 seconds; the request may still have arrived.")
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            return ContactResult(order_id, False, "uncertain",
                                 "No answer within 20 seconds; the request may still have arrived.")
        return ContactResult(order_id, False, "failed", f"Could not reach the routine ({exc.reason}).")


# --- Contact log -------------------------------------------------------------
# One JSON line per attempt, so the Contact Sellers page can show which orders
# already have a draft requested (and by whom) across reruns and sessions.

CONTACT_LOG = Path(__file__).resolve().parents[2] / "data" / "seller_contacts.jsonl"


def record_contact(result: ContactResult, *, manager: str, path: Path = CONTACT_LOG) -> dict:
    entry = {
        "order_id": result.order_id,
        "status": result.status,
        "detail": result.detail,
        "manager": manager,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    return entry


def latest_contacts(path: Path = CONTACT_LOG) -> dict[str, dict]:
    """Most recent attempt per order id."""
    latest: dict[str, dict] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entry = json.loads(line)
                latest[entry["order_id"]] = entry
    return latest

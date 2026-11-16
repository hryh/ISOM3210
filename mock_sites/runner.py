"""Start the mock supplier sites inside the current process when they are not
already running, so the Streamlit app works without a second terminal (and on
a single-process host such as Streamlit Community Cloud)."""

from __future__ import annotations

import threading
import time
import urllib.request
from urllib.parse import urlparse

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "0.0.0.0"}


def is_up(base_url: str, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(f"{base_url.rstrip('/')}/health", timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def ensure_mock_sites(base_url: str, wait_seconds: float = 15.0) -> bool:
    """Return True once ``base_url`` answers /health, starting the server if needed.

    Only starts a server for a local URL; a remote MOCK_BASE_URL is left alone.
    """
    if is_up(base_url):
        return True
    parsed = urlparse(base_url)
    if parsed.hostname not in _LOCAL_HOSTS:
        return False

    import uvicorn

    from .server import app

    config = uvicorn.Config(app, host="127.0.0.1", port=parsed.port or 80, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, name="mock-sites", daemon=True).start()

    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if is_up(base_url):
            return True
        time.sleep(0.3)
    return False

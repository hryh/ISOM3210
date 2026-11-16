"""Start what the app needs when it runs as a single process (Streamlit Cloud).

Locally you can still run the mock sites yourself (`uvicorn mock_sites.server:app
--port 8100`); if they are already up, nothing is started twice.

On a Linux server with no display (Streamlit Cloud):
- the mock supplier sites + portal start inside this process,
- Chrome for Testing is installed once and exported as ``CHROME_PATH``,
- Chrome runs headless and without its sandbox (containers can't use it).
"""

from __future__ import annotations

import os


def start() -> dict:
    from mock_sites.runner import ensure_mock_sites

    from .browser_setup import ensure_chrome, is_linux_server

    if is_linux_server():
        os.environ.setdefault("STAGEHAND_HEADLESS", "true")
        os.environ.setdefault("CI", "true")  # Stagehand then launches Chrome with --no-sandbox

    base = os.getenv("MOCK_BASE_URL", "http://127.0.0.1:8100")
    sites_ok = ensure_mock_sites(base)
    chrome = ensure_chrome() if is_linux_server() else None
    return {"sites_ok": sites_ok, "chrome": chrome}

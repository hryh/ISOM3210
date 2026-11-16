"""Make a Chrome available to Stagehand when running on a Linux server.

On Windows/macOS nothing happens here: Stagehand finds the installed Chrome.

On a Linux server (e.g. Streamlit Community Cloud) the distro's ``chromium``
package can be too old for Stagehand's extension loading, so on first start we
download the current "Chrome for Testing" build into the user's cache and point
``CHROME_PATH`` at it. ``packages.txt`` still installs the distro ``chromium``,
which pulls in the shared libraries Chrome needs and acts as a fallback.

Auto-install runs only when ``AUTO_INSTALL_CHROME=true`` or when the app is
running on Streamlit Community Cloud (repo checked out under ``/mount/src``).
"""

from __future__ import annotations

import json
import os
import sys
import threading
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path

CFT_INDEX = (
    "https://googlechromelabs.github.io/chrome-for-testing/"
    "last-known-good-versions-with-downloads.json"
)

_lock = threading.Lock()


def is_linux_server() -> bool:
    """Linux with no display attached, i.e. a server/container."""
    return sys.platform.startswith("linux") and not os.environ.get("DISPLAY")


def _truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes"}


def auto_install_enabled() -> bool:
    return _truthy("AUTO_INSTALL_CHROME") or Path("/mount/src").is_dir()


def install_dir() -> Path:
    return Path(os.getenv("CHROME_INSTALL_DIR", Path.home() / ".cache" / "purchasepilot-chrome"))


def _installed_binary() -> Path | None:
    hits = sorted(install_dir().glob("*/chrome-linux64/chrome"))
    return hits[-1] if hits else None


def _download_chrome(log: Callable[[str], None]) -> Path:
    with urllib.request.urlopen(CFT_INDEX, timeout=30) as resp:
        stable = json.load(resp)["channels"]["Stable"]
    version = stable["version"]
    url = next(d["url"] for d in stable["downloads"]["chrome"] if d["platform"] == "linux64")

    target = install_dir() / version
    target.mkdir(parents=True, exist_ok=True)
    archive = target / "chrome-linux64.zip"
    log(f"Downloading Chrome {version} (first run only)…")
    urllib.request.urlretrieve(url, archive)

    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            path = Path(zf.extract(info, target))
            mode = (info.external_attr >> 16) & 0o777
            if mode:  # zipfile drops unix permissions; restore them (chrome must be executable)
                path.chmod(mode)
    archive.unlink(missing_ok=True)
    return target / "chrome-linux64" / "chrome"


def ensure_chrome(log: Callable[[str], None] = lambda _m: None) -> str | None:
    """Return the Chrome path to use (also exported as ``CHROME_PATH``), or ``None``
    to let Stagehand find the system Chrome."""
    configured = os.getenv("CHROME_PATH")
    if configured and os.access(configured, os.X_OK):
        return configured
    if not sys.platform.startswith("linux") or not auto_install_enabled():
        return None

    with _lock:
        binary = _installed_binary()
        if binary is None:
            try:
                binary = _download_chrome(log)
            except Exception as exc:  # fall back to the distro chromium, if any
                log(f"Chrome download failed ({exc}); trying the system chromium.")
                return None
        os.environ["CHROME_PATH"] = str(binary)
        return str(binary)

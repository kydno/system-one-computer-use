"""The mock OS page in a dedicated Chromium: started, sized, loaded with a task, and read back.

Chromium is the one `browser/cdp.py` starts, on a throwaway profile with a loopback-only debugging
socket. Every host name is left unresolved, so a stray real URL cannot load; the display is fixed
at 1440 x 900 at scale 1, headless or headed, so the two render the same size.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ..browser.cdp import CDPError, Chrome, Session

WEB = Path(__file__).resolve().parent / "web"
INDEX = WEB / "index.html"
DISPLAY = (1440, 900)
LATENCIES = ("instant", "typical", "slow")
READY_SECONDS = 10.0

# Chromium's own flags for a page that must render the same every time and reach nothing.
FLAGS = (
    "--host-resolver-rules=MAP * ~NOTFOUND",  # no host name resolves, so nothing outside the page loads
    "--no-proxy-server",
    "--force-device-scale-factor=1",
    "--hide-scrollbars",
    "--disable-smooth-scrolling",
    "--font-render-hinting=none",
    "--disable-lcd-text",
    "--disable-renderer-backgrounding",  # a covered or minimized headed window keeps rendering
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    f"--window-size={DISPLAY[0]},{DISPLAY[1] + 120}",
)


class MockPage:
    """One Chromium with the mock OS loaded. `session` is the CDP session the adapter drives."""

    def __init__(self, *, headed: bool = False) -> None:
        self.headed = headed
        self.chrome = Chrome(headed=headed, extra_args=FLAGS)
        self.session: Session | None = None
        self.version: str | None = None

    def start(self) -> MockPage:
        self.chrome.start(window=DISPLAY)
        try:
            self.session = self.chrome.attach()
            self.version = (self.session.call("Browser.getVersion") or {}).get("product")
            width, height = DISPLAY
            self.session.call(
                "Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False}
            )
            self.session.call("Page.navigate", {"url": INDEX.as_uri()})
            self._wait_ready()
        except BaseException:
            self.close()
            raise
        return self

    def _wait_ready(self) -> None:
        deadline = time.monotonic() + READY_SECONDS
        while time.monotonic() < deadline:
            try:
                if self.js("typeof MockOS !== 'undefined' && MockOS.ready === true"):
                    return
            except CDPError:
                pass
            time.sleep(0.05)
        raise CDPError(f"the mock OS page did not load from {INDEX}")

    def js(self, expression: str) -> Any:
        if self.session is None:
            raise CDPError("the mock OS page is not started")
        return self.session.evaluate(expression)

    def call(self, name: str, *args: Any) -> Any:
        """Call `MockOS.<name>(*args)` in the page, the arguments passed as JSON."""
        return self.js(f"MockOS.{name}({', '.join(json.dumps(a) for a in args)})")

    def load(self, seed: dict, latency: str = "typical") -> None:
        if latency not in LATENCIES:
            raise ValueError(f"latency must be one of {LATENCIES}, not {latency!r}")
        self.call("load", seed, {"latency": latency})

    def dump(self) -> dict:
        return self.call("dump")

    def __enter__(self) -> MockPage:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self.session is not None:
            self.session.close()
            self.session = None
        self.chrome.close()

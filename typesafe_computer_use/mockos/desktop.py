"""The `Desktop` surface over the mock OS page, so the loop drives it unchanged, as it drives a Mac.

Every read of the screen comes from one snapshot: `screenshot()` holds the page's scheduler, reads
the app in front, its window, the focused field, the controls and every line of text in one call,
captures the pixels, and releases the scheduler, so all of them describe the same instant. The
queries that follow (`frontmost_app_and_pid`, `focused_field`, `actionable_elements`, ...) answer
from that snapshot with no round trip. Any input marks it stale, and the next query takes a new one.

Text is read from the page by default (`dom`): every rendered line with its box, deterministic and a
few milliseconds. `rapidocr` and `vision` hand the image to a real OCR backend instead, for the day
perception itself is the question. A crop of a capture says where it came from (see `_Capture`), so
the text in a crop is the snapshot's lines that fall inside it.

Input goes in as real input events over CDP: it never touches this machine's own pointer or keyboard.
A press through accessibility is a DOM click, as Chromium answers AXPress, so a control that listens
only to pointer events takes it and does nothing, and the loop falls back to a pointer click.
"""

from __future__ import annotations

import base64
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

from PIL import Image

from ..ax_walk import AX_PRESS, AxAttrs, walk_actionable
from ..models import AxNode, Field, KeyboardFocus
from ..platform_adapter import OcrLine
from .page import DISPLAY

BROWSER = "Chromium"  # the mock browser's name, one of config.BROWSER_APPS
LINE_PX = 40  # CSS pixels one scroll line moves; the loop scrolls ten at a time, most of a pane
DRAG_MOVES = 8
KEPT_SNAPSHOTS = 16  # snapshots kept by id, for a capture whose text is read after a newer one was taken
MODIFIERS = {"option": 1, "control": 2, "command": 4, "shift": 8}  # CDP's bits: Alt, Ctrl, Meta, Shift
BUTTONS = {"left": 1, "right": 2, "middle": 4}

# The loop's key names onto CDP's: (key, code, Windows virtual key code, text it types).
KEYS = {
    "return": ("Enter", "Enter", 13, "\r"),
    "escape": ("Escape", "Escape", 27, ""),
    "delete": ("Backspace", "Backspace", 8, ""),
    "forward_delete": ("Delete", "Delete", 46, ""),
    "tab": ("Tab", "Tab", 9, ""),
    "space": (" ", "Space", 32, " "),
    "up": ("ArrowUp", "ArrowUp", 38, ""),
    "down": ("ArrowDown", "ArrowDown", 40, ""),
    "left": ("ArrowLeft", "ArrowLeft", 37, ""),
    "right": ("ArrowRight", "ArrowRight", 39, ""),
    "page_up": ("PageUp", "PageUp", 33, ""),
    "page_down": ("PageDown", "PageDown", 34, ""),
    "home": ("Home", "Home", 36, ""),
    "end": ("End", "End", 35, ""),
}
PUNCTUATION_CODES = {"[": ("BracketLeft", 219), "]": ("BracketRight", 221), ",": ("Comma", 188), ".": ("Period", 190)}

Script = Callable[..., object]  # a call into the page: MockPage.call


class _Capture(Image.Image):
    """A screenshot that remembers which snapshot it shows and, once cropped, where the crop came from.

    The loop crops a capture before reading its text (`perception.ocr_crop`, `actions.read_back`) and
    hands over only the crop, so a crop records its own origin, added to its parent's, in its `info`.
    Pillow copies `info` into a crop, which carries the snapshot id along.
    """

    def crop(self, box=None):
        out = super().crop(box)
        if box is not None:
            ox, oy = self.info.get("origin", (0, 0))
            out.info["origin"] = (ox + round(box[0]), oy + round(box[1]))
        out.__class__ = _Capture
        return out


def capture_from_png(png: bytes, snapshot: int) -> Image.Image:
    image = Image.open(BytesIO(png)).convert("RGB")
    image.__class__ = _Capture
    image.info["snapshot"] = snapshot
    image.info.pop("origin", None)
    return image


@dataclass(frozen=True, eq=False)
class Node:
    """One control, or one piece of static text, of a snapshot's tree. Compared by identity: the walk
    keys a node it has seen by its hash."""

    id: int
    role: str
    label: str
    frame: tuple[float, float, float, float] | None
    press: bool
    children: tuple[Node, ...] = field(default=())

    @staticmethod
    def of(raw: dict) -> Node:
        frame = raw.get("frame")
        return Node(
            id=int(raw.get("id") or 0),
            role=str(raw.get("role") or ""),
            label=str(raw.get("label") or ""),
            frame=tuple(float(v) for v in frame) if frame else None,
            press=bool(raw.get("press")),
            children=tuple(Node.of(kid) for kid in raw.get("children") or ()),
        )


@dataclass(frozen=True)
class FieldRef:
    """The focused text field, by the page's id for its element."""

    id: int


def _id(ref) -> int | None:
    return ref.id if isinstance(ref, Node | FieldRef) and ref.id else None


class MockDesktop:
    """The mock OS as the computer the loop drives. `call` runs `MockOS.<name>(*args)` in the page, and
    `cdp` sends one CDP command; both are the page's (`MockPage.call`, `MockPage.session.call`)."""

    def __init__(self, call: Script, cdp: Callable[[str, dict], dict], *, ocr: str = "dom") -> None:
        self._call = call
        self._cdp = cdp
        self.ocr = ocr
        self._read: Callable[[Image.Image], list[OcrLine]] | None = None
        if ocr != "dom":
            from ..osworld import ocr as backends  # imported here: RapidOCR is an optional install

            self._read = backends.backend(ocr)
        self._snap: dict | None = None
        self._kept: dict[int, dict] = {}
        self._tree: tuple[int, Node] | None = None
        self.inputs = 0  # input events sent, for the record

    def __repr__(self) -> str:
        return f"<MockDesktop, ocr={self.ocr}>"

    # ----- snapshots -------------------------------------------------------------------------

    def _keep(self, snap: dict) -> dict:
        self._snap = snap
        self._kept[int(snap["id"])] = snap
        while len(self._kept) > KEPT_SNAPSHOTS:
            del self._kept[min(self._kept)]
        return snap

    def _now(self) -> dict:
        """The screen as it is now: the latest snapshot, or a new one when input has made it stale."""
        if self._snap is None:
            self._keep(self._call("snapshot"))
        return self._snap

    def _input(self) -> None:
        self._snap = None
        self.inputs += 1

    # ----- the escape hatch ------------------------------------------------------------------

    def check_abort(self) -> None:
        """Nothing to check: the mock has no pointer of the user's to slam into a corner."""

    def abort_hint(self) -> str:
        return "Ctrl-C"

    def sleep_watching(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)

    def accessibility_trusted(self) -> bool:
        return True

    # ----- input -----------------------------------------------------------------------------

    def _mouse(self, kind: str, x: float, y: float, **extra) -> None:
        self._cdp("Input.dispatchMouseEvent", {"type": kind, "x": float(x), "y": float(y), **extra})

    def click_at(self, point: tuple[float, float], button: str = "left", count: int = 1) -> None:
        x, y = point
        self._mouse("mouseMoved", x, y)
        for n in range(1, count + 1):
            self._mouse("mousePressed", x, y, button=button, buttons=BUTTONS.get(button, 1), clickCount=n)
            self._mouse("mouseReleased", x, y, button=button, buttons=0, clickCount=n)
        self._input()

    def press(self, key: str, command: bool = False, shift: bool = False, option: bool = False, control: bool = False) -> None:
        held = {"command": command, "shift": shift, "option": option, "control": control}
        modifiers = sum(bit for name, bit in MODIFIERS.items() if held[name])
        if key in KEYS:
            name, code, vk, text = KEYS[key]
        elif len(key) == 1:
            name = key.upper() if shift and key.isalpha() else key
            code, vk = PUNCTUATION_CODES.get(key, (f"Key{key.upper()}" if key.isalpha() else f"Digit{key}", ord(key.upper())))
            text = name
        else:
            raise ValueError(f"no key named {key!r}")
        typed = text if text and not (command or control or option) else ""
        event = {"modifiers": modifiers, "key": name, "code": code, "windowsVirtualKeyCode": vk}
        self._cdp(
            "Input.dispatchKeyEvent",
            {"type": "keyDown" if typed else "rawKeyDown", **event, **({"text": typed} if typed else {})},
        )
        self._cdp("Input.dispatchKeyEvent", {"type": "keyUp", **event})
        self._input()

    def drag(self, start: tuple[float, float], end: tuple[float, float]) -> None:
        (x1, y1), (x2, y2) = start, end
        self._mouse("mouseMoved", x1, y1)
        self._mouse("mousePressed", x1, y1, button="left", buttons=1, clickCount=1)
        for n in range(1, DRAG_MOVES + 1):
            t = n / DRAG_MOVES
            self._mouse("mouseMoved", x1 + (x2 - x1) * t, y1 + (y2 - y1) * t, button="left", buttons=1)
        self._mouse("mouseReleased", x2, y2, button="left", buttons=0, clickCount=1)
        self._input()

    def type_text(self, text: str) -> None:
        self._cdp("Input.insertText", {"text": text})
        self._input()

    def clear_field(self) -> None:
        self._call("clearField")
        self._input()

    def scroll(self, lines: int, at: tuple[float, float] | None = None) -> None:
        """A wheel under the pointer at `at`, or over the window's center, as the Mac adapter parks it."""
        if at is None:
            window = self.frontmost_window_bounds()
            x, y, w, h = window if window is not None else (0.0, 0.0, *DISPLAY)
            at = (x + w / 2, y + h / 2)
        self._mouse("mouseWheel", at[0], at[1], deltaX=0, deltaY=-lines * LINE_PX)
        self._input()

    def hover(self, at: tuple[float, float]) -> None:
        self._mouse("mouseMoved", at[0], at[1])
        self._input()

    # ----- apps and windows ------------------------------------------------------------------

    def frontmost_app_and_pid(self) -> tuple[str, int]:
        snap = self._now()
        return str(snap["app"]), int(snap["pid"])

    def activate(self, app: str, timeout: float = 3.0) -> bool:
        launched = bool(self._call("launch", app))
        self._input()
        return launched

    def open_url(self, browser: str, url: str) -> bool:
        """No mock browser yet: it comes with the fake sites (see docs/mock-os-plan.md)."""
        return False

    def installed_browsers(self) -> list[str]:
        """None to choose between: the one browser is the run's own."""
        return []

    def installed_apps(self) -> list[str]:
        return [name for name in self._call("apps") if name != BROWSER]

    def default_browser(self) -> str | None:
        return None

    def browser_url(self, browser: str) -> str | None:
        return self._now().get("url")

    def browser_tabs(self, browser: str) -> list[tuple[str, str]]:
        return [(str(title), str(url)) for title, url in self._now().get("tabs") or ()]

    def show_tab(self, browser: str, url: str) -> bool:
        return False

    def open_path(self, path: Path, as_text: bool = False) -> None:
        raise NotImplementedError("the mock OS shows no file of this machine's")

    def frontmost_window_bounds(self, pid: int | None = None) -> tuple[float, float, float, float] | None:
        window = self._now().get("window")
        return tuple(float(v) for v in window) if window else None

    # ----- capture, OCR, and accessibility ---------------------------------------------------

    def screenshot(self) -> Image.Image:
        snap = self._call("hold")
        try:
            shot = self._cdp("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
        finally:
            self._call("release")
        self._keep(snap)
        return capture_from_png(base64.b64decode(shot["data"]), int(snap["id"]))

    def display_scale(self, image: Image.Image) -> float:
        return 1.0

    def recognize_text(self, image: Image.Image) -> list[OcrLine]:
        if self._read is not None:
            return self._read(image)
        snap = self._kept.get(image.info.get("snapshot")) or self._now()
        return lines_in(snap["lines"], image.info.get("origin", (0, 0)), image.size)

    def focused_field(self, pid: int | None = None) -> Field | None:
        focus = self._now().get("focus")
        if not focus:
            return None
        x, y, w, h = (float(v) for v in focus["frame"])
        return Field(
            role=str(focus["role"]),
            label=str(focus["label"]),
            placeholder=str(focus["placeholder"]),
            value=str(focus["value"]),
            x=x,
            y=y,
            w=w,
            h=h,
            ref=FieldRef(int(focus["id"])),
            caret=focus.get("caret"),
            selected=str(focus.get("selected") or ""),
        )

    def keyboard_focus(self) -> KeyboardFocus | None:
        app, pid = self.frontmost_app_and_pid()
        return KeyboardFocus(app=app, pid=pid)

    def actionable_elements(self, pid: int, display_w_pt: float, display_h_pt: float) -> tuple[list[AxNode], list[AxNode], bool]:
        snap = self._now()
        if self._tree is None or self._tree[0] != snap["id"]:
            self._tree = (snap["id"], Node.of(snap["tree"]))
        return walk_actionable(
            self._tree[1],
            children=lambda node: node.children,
            attrs=lambda node: AxAttrs(node.role, node.label, node.frame),
            actions=lambda node: (AX_PRESS,) if node.press else (),
            display_w_pt=display_w_pt,
            display_h_pt=display_h_pt,
        )

    # ----- acting on an element --------------------------------------------------------------

    def ax_press(self, ref) -> bool:
        target = _id(ref)
        if target is None:
            return False
        pressed = bool(self._call("ax.press", target))
        self._input()
        return pressed

    def ax_focus(self, ref) -> bool:
        target = _id(ref)
        if target is None:
            return False
        focused = bool(self._call("ax.focus", target))
        self._input()
        return focused

    def ax_set_value(self, ref, text: str) -> bool:
        target = _id(ref)
        if target is None:
            return False
        done = bool(self._call("ax.setValue", target, text))
        self._input()
        return done

    def ax_value(self, ref) -> str | None:
        target = _id(ref)
        if target is None:
            return None
        value = self._call("ax.value", target)
        return None if value is None else str(value)


def lines_in(lines: list, origin: tuple[int, int], size: tuple[int, int]) -> list[OcrLine]:
    """The snapshot's lines whose centre falls inside the crop at `origin` of `size`, in the crop's own
    pixels, as an OCR backend would return them for that crop."""
    ox, oy = origin
    w, h = size
    out: list[OcrLine] = []
    for text, confidence, (x1, y1, x2, y2) in lines:
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        if ox <= cx < ox + w and oy <= cy < oy + h:
            out.append((str(text), float(confidence), (x1 - ox, y1 - oy, x2 - ox, y2 - oy)))
    return out

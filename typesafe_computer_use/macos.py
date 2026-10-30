"""macOS adapter: synthetic input, app control, screen capture, and the focused accessibility element.

This is the only module that touches Quartz, ApplicationServices, AppleScript, or Vision OCR.
windows.py provides the same functions for Windows; platform_adapter.py picks one. The bounded tree
walk itself lives in ax_walk.py, shared by both.
"""

from __future__ import annotations

import subprocess
import tempfile
import time
from collections.abc import Callable
from functools import partial
from pathlib import Path

import AppKit
import ApplicationServices as AS
import Quartz
from ocrmac import ocrmac
from PIL import Image

from .ax_walk import AX_PRESS, AxAttrs, Frame, walk_actionable
from .config import ABORT_CORNER_PX
from .models import TEXT_ROLES, Abort, AxNode, Field, KeyboardFocus

KEYCODES = {"return": 36, "tab": 48, "escape": 53, "a": 0, "delete": 51, "[": 33}
# Browsers name, on any element inside editable page content, the element its editing belongs to.
# A focused element with one and no text role is a rich-text editor, such as a Google Doc's hidden
# key box, which reports itself as a bare AXGroup.
EDITABLE_ANCESTOR = "AXEditableAncestor"
# Brave names no editable ancestor for that key box when its page is out of accessibility, but its
# DOM id still says what it is. Docs, Sheets and Slides all take their keys in one of these.
GOOGLE_KEY_BOX = "docs-texteventtarget"
MIN_WINDOW_SIDE_PT = 50.0  # anything smaller is a palette or a shadow, not the window being worked in

# The browsers use_browser can work in, by the name the frontmost app reports: Chromium's AppleScript
# dictionary, which open_url and browser_url speak.
BROWSERS = ("Google Chrome", "Brave Browser", "Microsoft Edge", "Arc", "Chromium")
APP_FOLDERS = (Path("/Applications"), Path.home() / "Applications")
# Where open_app looks: the folders above, the system's own apps (Photos, Notes, Calendar), and the
# Utilities inside each.
APP_FOLDERS_ALL = tuple(
    folder / sub for folder in (*APP_FOLDERS, Path("/System/Applications")) for sub in (Path(), Path("Utilities"))
)

# ------------------------------------------------------------------ escape hatch


def mouse_location() -> tuple[float, float]:
    loc = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
    return loc.x, loc.y


def check_abort() -> None:
    x, y = mouse_location()
    if x <= ABORT_CORNER_PX and y <= ABORT_CORNER_PX:
        raise Abort("mouse in top-left corner")


def abort_hint() -> str:
    return "Ctrl-C, or slam the mouse into the top-left corner"


def sleep_watching(seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        check_abort()
        time.sleep(0.1)


def accessibility_trusted() -> bool:
    return bool(AS.AXIsProcessTrusted())


# ------------------------------------------------------------------ input


def _post(event) -> None:
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
    time.sleep(0.04)


def _down_then_up(event: Callable[[bool], object]) -> None:
    """Post the down event, then the up event even when the down is interrupted, so nothing stays held."""
    try:
        _post(event(True))
    finally:
        _post(event(False))


def click_at(point: tuple[float, float]) -> None:
    # Check before moving: the synthetic move would otherwise take the pointer out of the abort corner.
    check_abort()
    _post(Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventMouseMoved, point, Quartz.kCGMouseButtonLeft))
    check_abort()
    kinds = {True: Quartz.kCGEventLeftMouseDown, False: Quartz.kCGEventLeftMouseUp}
    _down_then_up(lambda down: Quartz.CGEventCreateMouseEvent(None, kinds[down], point, Quartz.kCGMouseButtonLeft))


def press(key: str, command: bool = False) -> None:
    check_abort()
    code = KEYCODES[key]

    def event(down: bool):
        e = Quartz.CGEventCreateKeyboardEvent(None, code, down)
        Quartz.CGEventSetFlags(e, Quartz.kCGEventFlagMaskCommand if command else 0)
        return e

    _down_then_up(event)


def _unicode_key(ch: str, down: bool):
    """A key event carrying one character, with no modifier held.

    An event made without a source takes the modifiers the session last saw, and a Cmd-flagged
    press such as clear_field's Cmd+A leaves Command among them: "Barcelona" then went in as
    Cmd+B, Cmd+A, ... and its n opened a new browser window. The flags are set, never inherited.
    """
    event = Quartz.CGEventCreateKeyboardEvent(None, 0, down)
    Quartz.CGEventKeyboardSetUnicodeString(event, len(ch), ch)
    Quartz.CGEventSetFlags(event, 0)
    return event


def type_text(text: str) -> None:
    """One character at a time, checking the abort corner before each. A line break is the Return key,
    which every editor reads as one; a character event carrying it is left to each app to read."""
    for ch in text:
        check_abort()
        if ch == "\n":
            press("return")
        else:
            _down_then_up(partial(_unicode_key, ch))


def clear_field() -> None:
    press("a", command=True)
    press("delete")


def scroll(lines: int, at: tuple[float, float] | None = None) -> None:
    """Scroll events go to the view under the cursor, so park it at `at` first, or over the
    frontmost window's center when no point is given."""
    point = at if at is not None else frontmost_window_center()
    check_abort()
    if point is not None:
        _post(Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventMouseMoved, point, Quartz.kCGMouseButtonLeft))
    _post(Quartz.CGEventCreateScrollWheelEvent(None, Quartz.kCGScrollEventUnitLine, 1, lines))


# ------------------------------------------------------------------ apps and windows


def osascript(script: str) -> str:
    return subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=True).stdout.strip()


def frontmost_app() -> str:
    return osascript('tell application "System Events" to get name of first application process whose frontmost is true')


def frontmost_app_and_pid() -> tuple[str, int]:
    """Name and pid of the frontmost process in one AppleScript round trip."""
    name, _, pid = osascript(
        'tell application "System Events" to tell (first application process whose frontmost is true) to get {name, unix id}'
    ).rpartition(", ")
    return name, int(pid)


def frontmost_pid() -> int:
    return int(osascript('tell application "System Events" to get unix id of first application process whose frontmost is true'))


def activate(app: str, timeout: float = 3.0) -> bool:
    """Bring an app to the front, starting it when it is not running, and confirm it got there."""
    check_abort()
    try:
        osascript(f'tell application "{app}" to activate')
    except subprocess.CalledProcessError:
        return False  # no app goes by that name
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        check_abort()
        if frontmost_app() == app:
            return True
        time.sleep(0.1)
    check_abort()
    try:
        osascript(f'tell application "System Events" to set frontmost of process "{app}" to true')
    except subprocess.CalledProcessError:
        return False  # still starting, or its process goes by another name than its bundle
    time.sleep(0.3)
    return frontmost_app() == app


def open_url(browser: str, url: str) -> bool:
    check_abort()
    osascript(f'tell application "{browser}" to open location "{url}"')
    return activate(browser)


def installed_browsers() -> list[str]:
    """The browsers in BROWSERS with an app bundle in an Applications folder. Reads the disk, nothing else."""
    return [name for name in BROWSERS if any((folder / f"{name}.app").is_dir() for folder in APP_FOLDERS)]


def installed_apps() -> list[str]:
    """Every app bundle in APP_FOLDERS_ALL by name, sorted, except the browsers, which use_browser
    reaches. A name AppleScript could not quote is left out. Reads the disk, nothing else."""
    names = {
        path.stem
        for folder in APP_FOLDERS_ALL
        if folder.is_dir()
        for path in folder.iterdir()
        if path.suffix == ".app" and not path.name.startswith(".")
    }
    return sorted((name for name in names if name not in BROWSERS and not set('"\\') & set(name)), key=str.lower)


def default_browser() -> str | None:
    """The browser macOS opens web links in, when it is one of BROWSERS; None for any other, such as Safari."""
    handler = _link_handler()
    name = Path(handler).stem if handler else None
    return name if name in BROWSERS else None


def _link_handler() -> str | None:
    """The path of the app LaunchServices opens https links with. Asks, and opens nothing."""
    link = AppKit.NSURL.URLWithString_("https://example.com/")
    app = AppKit.NSWorkspace.sharedWorkspace().URLForApplicationToOpenURL_(link)
    return str(app.path()) if app is not None else None


def browser_url(browser: str) -> str | None:
    try:
        return osascript(f'tell application "{browser}" to get URL of active tab of front window') or None
    except subprocess.CalledProcessError:
        return None


def open_path(path: Path, as_text: bool = False) -> None:
    """Show a file to the user; `as_text` opens it in the default text editor."""
    subprocess.run(["open", *(["-t"] if as_text else []), str(path)], check=False)


def frontmost_window_bounds(pid: int | None = None) -> tuple[float, float, float, float] | None:
    """The frontmost app's focused window as x, y, w, h in points.

    Accessibility names that window; Quartz only lists windows. Chrome in full screen draws its
    toolbar in a window of its own above the page's, so the topmost Quartz window is the toolbar,
    and a region cut to it never reads the page. Quartz's topmost window stands in when
    accessibility has no answer: not trusted, or an app that exposes no focused window.

    Pass the pid when the caller already has it; looking it up costs an AppleScript round trip.
    """
    pid = frontmost_pid() if pid is None else pid
    return _focused_window(pid) or _topmost_window(pid)


def _focused_window(pid: int) -> tuple[float, float, float, float] | None:
    app = AS.AXUIElementCreateApplication(pid)
    AS.AXUIElementSetMessagingTimeout(app, AX_MESSAGE_TIMEOUT)
    window = _ax_attr(app, AS.kAXFocusedWindowAttribute)
    frame = _ax_frame(window) if window is not None else None
    return frame if frame is not None and frame[2] > MIN_WINDOW_SIDE_PT and frame[3] > MIN_WINDOW_SIDE_PT else None


def _topmost_window(pid: int) -> tuple[float, float, float, float] | None:
    """The app's topmost on-screen window at the normal level. Pure Quartz, no AX needed."""
    options = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
    for window in Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID) or []:
        if window.get("kCGWindowOwnerPID") == pid and window.get("kCGWindowLayer") == 0:
            b = window["kCGWindowBounds"]
            if b["Width"] > MIN_WINDOW_SIDE_PT and b["Height"] > MIN_WINDOW_SIDE_PT:
                return float(b["X"]), float(b["Y"]), float(b["Width"]), float(b["Height"])
    return None


def frontmost_window_center(pid: int | None = None) -> tuple[float, float] | None:
    """Center of the frontmost app's topmost on-screen window, in points."""
    bounds = frontmost_window_bounds(pid)
    if bounds is None:
        return None
    x, y, w, h = bounds
    return x + w / 2, y + h / 2


# ------------------------------------------------------------------ capture and accessibility


def screenshot() -> Image.Image:
    path = Path(tempfile.mkdtemp()) / "screen.png"
    subprocess.run(["screencapture", "-x", "-D", "1", str(path)], check=True, capture_output=True)
    return Image.open(path).convert("RGB")


def display_scale(image: Image.Image) -> float:
    points_wide = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID()).size.width
    return image.width / points_wide


def recognize_text(image: Image.Image) -> list[tuple[str, float, tuple[float, float, float, float]]]:
    """Vision OCR lines as text, confidence, and a box in the image's own pixels."""
    return ocrmac.OCR(image, recognition_level="accurate").recognize(px=True)


def _ax_attr(element, name: str):
    """One attribute, or None. A dead or hostile element raises from the bridge; that is a miss, not a crash."""
    try:
        err, value = AS.AXUIElementCopyAttributeValue(element, name, None)
    except Exception:
        return None
    return value if err == 0 else None


def _app_name(pid: int) -> str:
    running = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
    return str(running.localizedName()) if running is not None else ""


def keyboard_focus() -> KeyboardFocus | None:
    """The app the keyboard goes to, as the system-wide accessibility element names it.

    It can differ from the app in front: a panel that takes keys without coming to the front keeps
    the keyboard with its own app. It can also be no app at all, with the error that said so.
    """
    try:
        err, app = AS.AXUIElementCopyAttributeValue(AS.AXUIElementCreateSystemWide(), AS.kAXFocusedApplicationAttribute, None)
    except Exception as e:
        err, app = type(e).__name__, None
    owner, owner_pid = "", None
    if err == 0 and app is not None:
        err, found = AS.AXUIElementGetPid(app, None)
        if err == 0:
            owner, owner_pid = _app_name(found), found
    return KeyboardFocus(owner, owner_pid, None if err == 0 else str(err))


def focused_field(pid: int | None = None) -> Field | None:
    """The focused element, asked of the whole system, and of the frontmost app `pid` when the
    system cannot say.

    The system-wide question can fail at once with -25204 for every app, whichever is in front,
    while the app asked itself still names its focused element: a Google Doc's key box went unseen
    that way, and a run that sees no field never types.
    """
    element = _ax_attr(AS.AXUIElementCreateSystemWide(), AS.kAXFocusedUIElementAttribute)
    if element is None and pid is not None:
        app = AS.AXUIElementCreateApplication(pid)
        AS.AXUIElementSetMessagingTimeout(app, AX_MESSAGE_TIMEOUT)
        element = _ax_attr(app, AS.kAXFocusedUIElementAttribute)
    if element is None:
        return None
    x = y = w = h = 0.0
    pos = _ax_attr(element, AS.kAXPositionAttribute)
    size = _ax_attr(element, AS.kAXSizeAttribute)
    if pos is not None and size is not None:
        _, pt = AS.AXValueGetValue(pos, AS.kAXValueCGPointType, None)
        _, sz = AS.AXValueGetValue(size, AS.kAXValueCGSizeType, None)
        x, y, w, h = pt.x, pt.y, sz.width, sz.height
    value = _ax_attr(element, AS.kAXValueAttribute)
    label = _ax_attr(element, AS.kAXTitleAttribute) or _ax_attr(element, AS.kAXDescriptionAttribute) or ""
    role = str(_ax_attr(element, AS.kAXRoleAttribute) or "")
    return Field(
        role=role,
        label=str(label),
        placeholder=str(_ax_attr(element, AS.kAXPlaceholderValueAttribute) or ""),
        value=value if isinstance(value, str) else "",
        x=x,
        y=y,
        w=w,
        h=h,
        ref=element,
        editor=role not in TEXT_ROLES
        and (
            _ax_attr(element, EDITABLE_ANCESTOR) is not None
            or str(_ax_attr(element, "AXDOMIdentifier") or "").startswith(GOOGLE_KEY_BOX)
        ),
    )


# ------------------------------------------------------------------ acting on an element

# An element accepts these directly, so a press lands on the control the app declared rather than
# on whatever pixel happens to sit at its center. Every one of them is best effort: the element may
# be dead, the app may refuse, and the bridge raises on both. False means "use synthetic input".


def ax_press(ref) -> bool:
    """Send AXPress to an element."""
    check_abort()
    try:
        return AS.AXUIElementPerformAction(ref, AX_PRESS) == 0
    except Exception:
        return False


def ax_focus(ref) -> bool:
    """Give an element the keyboard focus."""
    check_abort()
    try:
        return AS.AXUIElementSetAttributeValue(ref, AS.kAXFocusedAttribute, True) == 0
    except Exception:
        return False


def ax_set_value(ref, text: str) -> bool:
    """Write an element's value. A read-only or unwilling element reports an error."""
    check_abort()
    try:
        return AS.AXUIElementSetAttributeValue(ref, AS.kAXValueAttribute, text) == 0
    except Exception:
        return False


def ax_value(ref) -> str | None:
    """An element's value, when it has a textual one."""
    value = _ax_attr(ref, AS.kAXValueAttribute)
    return value if isinstance(value, str) else None


# ------------------------------------------------------------------ actionable elements

AX_MESSAGE_TIMEOUT = 0.2
AX_VALUE_CHARS = 120


def _ax_children(element) -> list:
    return list(_ax_attr(element, AS.kAXChildrenAttribute) or [])


def _ax_label(element) -> str:
    """AXTitle on AppKit, AXDescription on web and Electron, a short AXValue as a last resort."""
    for name in (AS.kAXTitleAttribute, AS.kAXDescriptionAttribute):
        text = _ax_attr(element, name)
        if isinstance(text, str) and text.strip():
            return " ".join(text.split())
    value = _ax_attr(element, AS.kAXValueAttribute)
    if isinstance(value, str) and 0 < len(value.strip()) <= AX_VALUE_CHARS:
        return " ".join(value.split())
    return ""


def _ax_frame(element) -> Frame | None:
    pos = _ax_attr(element, AS.kAXPositionAttribute)
    size = _ax_attr(element, AS.kAXSizeAttribute)
    if pos is None or size is None:
        return None
    ok_pos, pt = AS.AXValueGetValue(pos, AS.kAXValueCGPointType, None)
    ok_size, sz = AS.AXValueGetValue(size, AS.kAXValueCGSizeType, None)
    if not (ok_pos and ok_size):
        return None
    return float(pt.x), float(pt.y), float(sz.width), float(sz.height)


def _ax_attrs(element) -> AxAttrs:
    return AxAttrs(str(_ax_attr(element, AS.kAXRoleAttribute) or ""), _ax_label(element), _ax_frame(element))


def _ax_actions(element) -> list[str]:
    try:
        err, names = AS.AXUIElementCopyActionNames(element, None)
    except Exception:
        return []
    return [str(n) for n in names] if err == 0 and names else []


def actionable_elements(pid: int, display_w_pt: float, display_h_pt: float) -> tuple[list[AxNode], list[AxNode], bool]:
    """Labelled controls of one process: the on-screen ones in points, the pressable off-screen ones,
    and whether a cap cut the walk short."""
    app = AS.AXUIElementCreateApplication(pid)
    AS.AXUIElementSetMessagingTimeout(app, AX_MESSAGE_TIMEOUT)
    return walk_actionable(app, _ax_children, _ax_attrs, _ax_actions, display_w_pt, display_h_pt)

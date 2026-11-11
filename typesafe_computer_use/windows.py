"""Windows adapter: synthetic input, app control, screen capture, OCR, and the focused UI Automation element.

Experimental. This is the only module that touches pywin32, UI Automation, Win32 SendInput, or
Windows.Media.Ocr; macos.py provides the same functions for macOS, and platform_adapter.py picks one.
The bounded tree walk itself lives in ax_walk.py, shared by both.

Once the process is per-monitor DPI aware (set below), Windows has no Retina-style point and pixel
split, so a screen point here already is a capture pixel. The pure rules (the role names, what counts
as pressable, which window belongs to an app, the input events) are plain functions, tested off Windows.
"""

from __future__ import annotations

import ctypes
import functools
import os
import shutil
import subprocess
import time
import webbrowser
from contextlib import suppress
from pathlib import Path

import psutil
import uiautomation as auto
import win32api
import win32con
import win32gui
import win32process
import winocr
from PIL import Image, ImageGrab

from .ax_walk import AX_PRESS, AxAttrs, Frame, walk_actionable
from .config import ABORT_CORNER_PX
from .models import Abort, AxNode, Field, KeyboardFocus, Missed

with suppress(AttributeError, OSError):  # pre-8.1 Windows without shcore, or awareness set by the host process
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE

MIN_WINDOW_SIDE_PT = 50.0  # anything smaller is a palette or a shadow, not the window being worked in
EVENT_GAP = 0.04  # seconds between synthetic events, as on macOS
CLICK_TOLERANCE_PX = 1  # how far the cursor may land from its target before a click is refused
WHEEL_DELTA = 120  # one notch of the wheel
LINES_PER_NOTCH = 3  # the Windows default; the actions ask for lines, as on macOS

# Windows.Media.Ocr reads one language per engine and reports no confidence, so every line it returns
# counts as certain and passes MIN_OCR_CONFIDENCE. The language pack must be installed (see docs/windows.md).
OCR_LANGUAGE = "en"
OCR_CONFIDENCE = 1.0

# UI Automation's ControlTypeName mapped onto the "AX*" role vocabulary ax_walk.py, models.ROLE_WORDS,
# and models.TEXT_ROLES already speak, so none of that shared logic needs a Windows-specific branch.
CONTROL_TYPE_TO_ROLE = {
    "ButtonControl": "AXButton",
    "CheckBoxControl": "AXCheckBox",
    "ComboBoxControl": "AXComboBox",
    "DataItemControl": "AXCell",
    "EditControl": "AXTextField",
    "GroupControl": "AXGroup",
    "HyperlinkControl": "AXLink",
    "ImageControl": "AXImage",
    "ListItemControl": "AXRow",
    "MenuItemControl": "AXMenuBarItem",
    "RadioButtonControl": "AXRadioButton",
    "SliderControl": "AXSlider",
    "SpinnerControl": "AXIncrementor",
    "TabItemControl": "AXTab",
    "TextControl": "AXStaticText",
}

# The browsers the site catalog can open, by the name CLICKER_BROWSER gives and their executable.
# The frontmost app is reported by the same name, so the classifier sees one browser, not two.
BROWSER_EXES = {"Google Chrome": "chrome", "Microsoft Edge": "msedge", "Firefox": "firefox", "Brave Browser": "brave"}

# Virtual keys for the keys the actions press. macOS's Command becomes Control, except Command-[,
# a browser's Back, which is Alt-Left on Windows.
VK = {
    "return": 0x0D, "tab": 0x09, "escape": 0x1B, "delete": 0x2E, "left": 0x25, "right": 0x27, "up": 0x26, "down": 0x28,
    "page_up": 0x21, "page_down": 0x22,
    "[": 0xDB, "]": 0xDD, "=": 0xBB, "-": 0xBD,
    "a": 0x41, "b": 0x42, "c": 0x43, "d": 0x44, "f": 0x46, "i": 0x49, "l": 0x4C, "n": 0x4E, "o": 0x4F, "p": 0x50,
    "r": 0x52, "s": 0x53, "t": 0x54, "u": 0x55, "v": 0x56, "w": 0x57, "x": 0x58, "z": 0x5A,
}  # fmt: skip
VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_ALT = 0x12
EXTENDED_KEYS = {0x2E, 0x25, 0x26, 0x27, 0x28, 0x21, 0x22}  # Delete, the arrows and Page Up and Down: the extended keypad
COMMAND_CHORDS = {"[": (VK_ALT, VK["left"])}

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
BUTTON_EVENTS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
}
MAX_CLICKS = 3  # a click, a double click, and a triple click: the line or paragraph
DRAG_STEPS = 12  # moves between pressing and releasing, each with its own look at the abort corner
DRAG_HOLD = 0.15  # seconds the button is held before the first move and after the last: apps need it to start and to drop
MOUSEEVENTF_WHEEL = 0x0800


# ------------------------------------------------------------------ pure rules


def role_for(control_type_name: str) -> str:
    """The AX role a UI Automation control type stands for, or "" for one the walk ignores."""
    return CONTROL_TYPE_TO_ROLE.get(control_type_name, "")


def pressable(has_invoke: bool, default_action: str) -> bool:
    """Whether an element accepts a press. Almost every element carries the LegacyIAccessible
    pattern, so that pattern alone says nothing; only a named default action makes it a control."""
    return has_invoke or bool(default_action.strip())


def exe_stem(name: str) -> str:
    """`Chrome.exe`, `chrome` and ` CHROME ` are one process name."""
    stem = name.strip().lower()
    return stem.removesuffix(".exe")


def app_matches(app: str, process_name: str) -> bool:
    """Whether a process is the app a caller named: the executable itself, or a known browser by
    its product name. Exact, never a substring, and never by window title, so a Chrome tab named
    after an app is not that app."""
    wanted = exe_stem(app)
    browsers = {name.lower(): exe for name, exe in BROWSER_EXES.items()}
    return exe_stem(process_name) in {wanted, browsers.get(wanted, wanted)}


def display_name(process_name: str) -> str:
    """The name to report for a process: a known browser by its product name, anything else as is."""
    stem = exe_stem(process_name)
    return next((name for name, exe in BROWSER_EXES.items() if exe == stem), process_name)


def key_events(
    key: str, command: bool = False, shift: bool = False, option: bool = False, control: bool = False
) -> list[tuple[int, int]]:
    """(virtual key, flags) for pressing a key, with its modifiers held around it.

    Windows has one Control key, which stands for macOS's Command and its Control alike, and Alt is Option.
    Command with a key that has a chord of its own (`[` is Alt-Left) is that chord, with Shift if asked; Option
    or Control with it would be dropped silently, so that combination is refused.
    """
    if command and key in COMMAND_CHORDS:
        if option or control:
            raise ValueError(f"Command-{key} is {COMMAND_CHORDS[key]} on Windows and cannot also hold Option or Control")
        keys = COMMAND_CHORDS[key]
    else:
        keys = (*((VK_CONTROL,) if command or control else ()), *((VK_ALT,) if option else ()), VK[key])
    keys = (VK_SHIFT, *keys) if shift else keys
    down = [(vk, KEYEVENTF_EXTENDEDKEY if vk in EXTENDED_KEYS else 0) for vk in keys]
    up = [(vk, flags | KEYEVENTF_KEYUP) for vk, flags in reversed(down)]
    return down + up


def unicode_events(text: str) -> list[tuple[int, int]]:
    """(UTF-16 code unit, flags) for typing text as characters, not keys, so any script and any
    emoji arrive whatever the keyboard layout. A character outside the BMP is two units."""
    data = text.encode("utf-16-le")
    units = [int.from_bytes(data[i : i + 2], "little") for i in range(0, len(data), 2)]
    return [(unit, flags) for unit in units for flags in (KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)]


def wheel_delta(lines: int) -> int:
    """The wheel delta that scrolls `lines` lines; positive scrolls up, as on macOS."""
    return round(lines * WHEEL_DELTA / LINES_PER_NOTCH)


def landed(target: tuple[int, int], actual: tuple[float, float]) -> bool:
    return abs(actual[0] - target[0]) <= CLICK_TOLERANCE_PX and abs(actual[1] - target[1]) <= CLICK_TOLERANCE_PX


def ocr_lines(result: dict) -> list[tuple[str, float, tuple[float, float, float, float]]]:
    """winocr's plain-dict result as text, confidence, and a box around the line's words."""
    out = []
    for line in result.get("lines", []):
        rects = [word["bounding_rect"] for word in line.get("words", [])]
        if not rects:
            continue
        x1 = min(r["x"] for r in rects)
        y1 = min(r["y"] for r in rects)
        x2 = max(r["x"] + r["width"] for r in rects)
        y2 = max(r["y"] + r["height"] for r in rects)
        out.append((line["text"], OCR_CONFIDENCE, (float(x1), float(y1), float(x2), float(y2))))
    return out


# ------------------------------------------------------------------ SendInput


class _MouseInput(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_int32),
        ("dy", ctypes.c_int32),
        ("mouseData", ctypes.c_uint32),
        ("dwFlags", ctypes.c_uint32),
        ("time", ctypes.c_uint32),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _KeyboardInput(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_uint16),
        ("wScan", ctypes.c_uint16),
        ("dwFlags", ctypes.c_uint32),
        ("time", ctypes.c_uint32),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _InputUnion(ctypes.Union):
    _fields_ = [("mi", _MouseInput), ("ki", _KeyboardInput)]


class _Input(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint32), ("u", _InputUnion)]


@functools.cache
def _user32():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SendInput.argtypes = (ctypes.c_uint, ctypes.POINTER(_Input), ctypes.c_int)
    user32.SendInput.restype = ctypes.c_uint
    return user32


def _send(event: _Input) -> None:
    """One synthetic event, then the same pause macOS leaves. A blocked event (a UAC prompt or the
    lock screen has the input desktop) raises rather than going missing."""
    if _user32().SendInput(1, ctypes.byref(event), ctypes.sizeof(_Input)) != 1:
        raise ctypes.WinError(ctypes.get_last_error())
    time.sleep(EVENT_GAP)


def _key(vk: int = 0, scan: int = 0, flags: int = 0) -> _Input:
    return _Input(type=INPUT_KEYBOARD, u=_InputUnion(ki=_KeyboardInput(wVk=vk, wScan=scan, dwFlags=flags)))


def _mouse(flags: int, data: int = 0) -> _Input:
    return _Input(type=INPUT_MOUSE, u=_InputUnion(mi=_MouseInput(mouseData=data & 0xFFFFFFFF, dwFlags=flags)))


# ------------------------------------------------------------------ escape hatch


def mouse_location() -> tuple[float, float]:
    x, y = win32api.GetCursorPos()
    return float(x), float(y)


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
    """Windows has no Accessibility permission gate; confirm UI Automation can reach the desktop instead."""
    try:
        return auto.GetRootControl() is not None
    except Exception:
        return False


# ------------------------------------------------------------------ input


def _move(point: tuple[int, int]) -> None:
    win32api.SetCursorPos(point)
    time.sleep(EVENT_GAP)


def _reach(point: tuple[float, float]) -> tuple[int, int]:
    """Move the cursor to `point` and read back where it landed. A cursor that did not reach the
    target (another desktop has the input, or the point is off every monitor) would press somewhere
    unknown, so nothing is pressed."""
    target = (round(point[0]), round(point[1]))
    _move(target)
    actual = mouse_location()
    if not landed(target, actual):
        raise Missed(f"the cursor went to {actual}, not {target}")
    return target


def click_at(point: tuple[float, float], button: str = "left", count: int = 1) -> None:
    """Move, read back where the cursor landed, then press and release there `count` times with the
    left or right button; two clicks in a row are a double click. The abort corner is looked at
    between the clicks, and the button comes up even when the press is interrupted."""
    if button not in BUTTON_EVENTS or not 1 <= count <= MAX_CLICKS:
        raise ValueError(f"cannot click {count} times with the {button!r} button")
    down, up = BUTTON_EVENTS[button]
    check_abort()
    _reach(point)
    for n in range(count):
        if n:
            check_abort()
        try:
            _send(_mouse(down))
        finally:
            _send(_mouse(up))


def drag(start: tuple[float, float], end: tuple[float, float]) -> None:
    """Press the left button at `start`, move to `end` in steps, and release there.

    A drag that is interrupted or aborted half way goes back to `start` and lets go there, so nothing
    stays held and nothing is dropped where the cursor was passing over. The button-up event carries no
    position, so the cursor is moved to the release point first, never left where the user's hand took it
    (the abort corner).
    """
    check_abort()
    here = _reach(start)
    completed = False
    try:
        _send(_mouse(MOUSEEVENTF_LEFTDOWN))
        sleep_watching(DRAG_HOLD)
        for n in range(1, DRAG_STEPS + 1):
            check_abort()
            here = (
                round(start[0] + (end[0] - start[0]) * n / DRAG_STEPS),
                round(start[1] + (end[1] - start[1]) * n / DRAG_STEPS),
            )
            _move(here)
        sleep_watching(DRAG_HOLD)
        completed = True
    finally:
        try:
            _move(here if completed else _round_point(start))
        finally:
            _send(_mouse(MOUSEEVENTF_LEFTUP))


def _round_point(point: tuple[float, float]) -> tuple[int, int]:
    return (round(point[0]), round(point[1]))


def press(key: str, command: bool = False, shift: bool = False, option: bool = False, control: bool = False) -> None:
    """Press the key with its modifiers held around it. A key still held when an event fails (a UAC
    prompt or the lock screen takes the input desktop) is let go, so no modifier stays down."""
    held: list[tuple[int, int]] = []
    try:
        for vk, flags in key_events(key, command, shift, option, control):
            if not flags & KEYEVENTF_KEYUP:
                held.append((vk, flags))
            _send(_key(vk=vk, flags=flags))
            if flags & KEYEVENTF_KEYUP:
                held = [h for h in held if h[0] != vk]
    finally:
        for vk, flags in reversed(held):
            # One that cannot be let go (the input desktop is still locked) must not leave the others held,
            # and must not hide the error that got us here.
            with suppress(OSError):
                _send(_key(vk=vk, flags=flags | KEYEVENTF_KEYUP))


def type_text(text: str) -> None:
    for unit, flags in unicode_events(text):
        _send(_key(scan=unit, flags=flags))


def clear_field() -> None:
    press("a", command=True)
    press("delete")


def scroll(lines: int, at: tuple[float, float] | None = None) -> None:
    """Scroll events go to the view under the cursor, so park it at `at` first, or over the
    frontmost window's center when no point is given."""
    point = at if at is not None else frontmost_window_center()
    if point is not None:
        _move((round(point[0]), round(point[1])))
    _send(_mouse(MOUSEEVENTF_WHEEL, wheel_delta(lines)))


def hover(at: tuple[float, float]) -> None:
    """Park the cursor at `at` and press nothing, so what reacts to it there shows before a scroll."""
    _move((round(at[0]), round(at[1])))


# ------------------------------------------------------------------ apps and windows


def _process_name(pid: int) -> str:
    try:
        return psutil.Process(pid).name()
    except psutil.Error:
        return ""


def _window_pid(hwnd: int) -> int:
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    return pid


def frontmost_app() -> str:
    name, _ = frontmost_app_and_pid()
    return name


def frontmost_app_and_pid() -> tuple[str, int]:
    """Name and pid of the foreground window's process."""
    pid = frontmost_pid()
    return display_name(_process_name(pid)), pid


def frontmost_pid() -> int:
    return _window_pid(win32gui.GetForegroundWindow())


def _find_window(app: str) -> int | None:
    """The topmost visible, titled top-level window whose process is `app` (see app_matches)."""
    found: list[int] = []

    def visit(hwnd, _):  # returns None, so the enumeration runs to the end without raising
        titled = not found and win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd)
        if titled and app_matches(app, _process_name(_window_pid(hwnd))):
            found.append(hwnd)

    win32gui.EnumWindows(visit, None)  # top of the z-order first
    return found[0] if found else None


def activate(app: str, timeout: float = 3.0) -> bool:
    """Bring an app to the front and confirm it got there."""
    hwnd = _find_window(app)
    if hwnd is None:
        return False
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    with suppress(Exception):  # Windows may refuse focus theft; the check below reports it
        win32gui.SetForegroundWindow(hwnd)
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if win32gui.GetForegroundWindow() == hwnd:
            return True
        time.sleep(0.1)
    return win32gui.GetForegroundWindow() == hwnd


def open_url(browser: str, url: str) -> bool:
    exe = next((exe for name, exe in BROWSER_EXES.items() if name.lower() == browser.strip().lower()), None)
    if exe and shutil.which(exe):
        subprocess.Popen([exe, url])
    else:
        webbrowser.open(url)
    return activate(browser)


def installed_browsers() -> list[str]:
    """The browsers in BROWSER_EXES whose executable is on the PATH."""
    return [name for name, exe in BROWSER_EXES.items() if shutil.which(exe)]


def installed_apps() -> list[str]:
    """None: nothing here reads the Start menu yet, so open_app is not offered on Windows."""
    return []


def default_browser() -> str | None:
    """None: Windows keeps its link handler in the registry, which nothing here reads yet, so
    CLICKER_BROWSER or Chrome stands in."""
    return None


def browser_tabs(browser: str) -> list[tuple[str, str]]:
    """None: UI Automation shows each tab's title but not its URL, so no tab can be named by address."""
    return []


def show_tab(browser: str, url: str) -> bool:
    """False: with no tab named by address (see `browser_tabs`), use_browser opens the URL instead."""
    return False


def browser_url(browser: str) -> str | None:
    """The address bar's text, read through UI Automation. No AppleScript-style API exists for this
    on Windows, so it depends on the browser exposing an Edit control named for the address bar,
    which Chrome, Edge, and Firefox do. Chrome and Edge show it without the scheme."""
    hwnd = _find_window(browser)
    if hwnd is None:
        return None
    try:
        window = auto.ControlFromHandle(hwnd)
        edit = window.EditControl(searchDepth=20, RegexName="(?i)address")
        if not edit.Exists(0, 0):
            return None
        return _ui_value(edit) or None
    except Exception:
        return None


def open_path(path: Path, as_text: bool = False) -> None:
    """Show a file to the user in its default app; a .txt already opens in the text editor."""
    os.startfile(path)


def frontmost_window_bounds(pid: int | None = None) -> tuple[float, float, float, float] | None:
    """The foreground window's bounds as x, y, w, h in screen pixels.

    Pass the pid when the caller already has it, to confirm the foreground window still belongs
    to that process rather than one that grabbed focus since.
    """
    hwnd = win32gui.GetForegroundWindow()
    if pid is not None and _window_pid(hwnd) != pid:
        return None
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    w, h = float(right - left), float(bottom - top)
    if w > MIN_WINDOW_SIDE_PT and h > MIN_WINDOW_SIDE_PT:
        return float(left), float(top), w, h
    return None


def frontmost_window_center(pid: int | None = None) -> tuple[float, float] | None:
    """Center of the frontmost app's topmost on-screen window, in screen pixels."""
    bounds = frontmost_window_bounds(pid)
    if bounds is None:
        return None
    x, y, w, h = bounds
    return x + w / 2, y + h / 2


# ------------------------------------------------------------------ capture, OCR, and accessibility


def screenshot() -> Image.Image:
    """The primary monitor, the one macOS calls the main display."""
    return ImageGrab.grab().convert("RGB")


def display_scale(image: Image.Image) -> float:
    """Per-monitor DPI awareness keeps every coordinate in physical pixels, so a screen point
    already is a capture pixel; unlike macOS, there is no separate points-vs-pixels scale."""
    return 1.0


def recognize_text(image: Image.Image) -> list[tuple[str, float, tuple[float, float, float, float]]]:
    """Windows.Media.Ocr lines as text, confidence, and a box in the image's own pixels."""
    return ocr_lines(winocr.recognize_pil_sync(image, OCR_LANGUAGE))


def _pattern(element, pattern_id):
    """A UI Automation pattern, or None when the element does not support it or has died."""
    try:
        return element.GetPattern(pattern_id)
    except Exception:
        return None


def _ui_value(element) -> str | None:
    pattern = _pattern(element, auto.PatternId.ValuePattern)
    try:
        return pattern.Value if pattern is not None else None
    except Exception:
        return None


def _ui_placeholder(element) -> str:
    legacy = _pattern(element, auto.PatternId.LegacyIAccessiblePattern)
    try:
        return (legacy.Description or "") if legacy is not None else ""
    except Exception:
        return ""


def _ui_default_action(element) -> str:
    legacy = _pattern(element, auto.PatternId.LegacyIAccessiblePattern)
    try:
        return (legacy.DefaultAction or "") if legacy is not None else ""
    except Exception:
        return ""


def focused_field(pid: int | None = None) -> Field | None:
    """The focused control. UI Automation always names it, so the frontmost `pid` is not needed."""
    try:
        element = auto.GetFocusedControl()
    except Exception:
        return None
    if element is None:
        return None
    frame = _ui_frame(element)
    x, y, w, h = frame if frame is not None else (0.0, 0.0, 0.0, 0.0)
    return Field(
        role=role_for(getattr(element, "ControlTypeName", "")),
        label=(getattr(element, "Name", "") or "").strip(),
        placeholder=_ui_placeholder(element),
        value=_ui_value(element) or "",
        x=x,
        y=y,
        w=w,
        h=h,
        ref=element,
    )


def keyboard_focus() -> KeyboardFocus | None:
    """Nothing to report: Windows sends the keys to the foreground window, the one the run reads."""
    return None


# ------------------------------------------------------------------ acting on an element

# An element accepts these directly, so a press lands on the control the app declared rather than
# on whatever pixel happens to sit at its center. Every one of them is best effort: the element may
# be dead, the app may refuse, and the bridge raises on both. False means "use synthetic input".


def ax_press(ref) -> bool:
    """Invoke an element, or run its named legacy default action: the same rule as `pressable`."""
    invoke = _pattern(ref, auto.PatternId.InvokePattern)
    try:
        if invoke is not None:
            invoke.Invoke()
            return True
        if _ui_default_action(ref).strip():
            _pattern(ref, auto.PatternId.LegacyIAccessiblePattern).DoDefaultAction()
            return True
    except Exception:
        pass
    return False


def ax_focus(ref) -> bool:
    """Give an element the keyboard focus."""
    try:
        return bool(ref.SetFocus())
    except Exception:
        return False


def ax_set_value(ref, text: str) -> bool:
    """Write an element's value. A read-only or unwilling element reports an error."""
    pattern = _pattern(ref, auto.PatternId.ValuePattern)
    try:
        return pattern is not None and bool(pattern.SetValue(text))
    except Exception:
        return False


def ax_value(ref) -> str | None:
    """An element's value, when it has a textual one."""
    return _ui_value(ref)


# ------------------------------------------------------------------ actionable elements


def _ui_children(element) -> list:
    try:
        return list(element.GetChildren())
    except Exception:
        return []


def _ui_frame(element) -> Frame | None:
    try:
        rect = element.BoundingRectangle
    except Exception:
        return None
    if rect is None:
        return None
    return float(rect.left), float(rect.top), float(rect.width()), float(rect.height())


def _ui_attrs(element) -> AxAttrs:
    label = (getattr(element, "Name", "") or "").strip()
    return AxAttrs(role_for(getattr(element, "ControlTypeName", "")), label, _ui_frame(element))


def _ui_actions(element) -> list[str]:
    has_invoke = _pattern(element, auto.PatternId.InvokePattern) is not None
    return [AX_PRESS] if pressable(has_invoke, "" if has_invoke else _ui_default_action(element)) else []


def actionable_elements(pid: int, display_w_pt: float, display_h_pt: float) -> tuple[list[AxNode], list[AxNode], bool]:
    """Labelled controls of the foreground window, in screen pixels, and the pressable off-screen
    ones. Best effort: a window that refuses UI Automation, or belongs to a different process, or
    has none, yields nothing."""
    hwnd = win32gui.GetForegroundWindow()
    if _window_pid(hwnd) != pid:
        return [], [], False
    try:
        root = auto.ControlFromHandle(hwnd)
    except Exception:
        return [], [], False
    return walk_actionable(root, _ui_children, _ui_attrs, _ui_actions, display_w_pt, display_h_pt)

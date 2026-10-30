"""Every adapter provides the whole Desktop surface, macOS stays the default, and a block can swap in another."""

import inspect
import sys
from types import SimpleNamespace

import pytest

from typesafe_computer_use import macos, windows
from typesafe_computer_use.models import KeyboardFocus
from typesafe_computer_use.osworld.desktop import OSWorldDesktop
from typesafe_computer_use.platform_adapter import Desktop, NoDesktop, current, desktop, host, pick_host, using

SURFACE = sorted(name for name, value in vars(Desktop).items() if callable(value) and not name.startswith("_"))
KEYBOARD_FOCUS = macos.keyboard_focus  # read at collection, before the conftest guard refuses it


def shape(function) -> list[tuple[str, object, object]]:
    """Parameter names, kinds and defaults: what a caller relies on, without the annotations."""
    params = list(inspect.signature(function).parameters.values())
    if params and params[0].name == "self":
        params = params[1:]
    return [(p.name, p.kind, p.default) for p in params]


# Read at collection, before the conftest guard swaps the machine-touching functions for refusals.
PROVIDED = {
    (adapter.__name__, name): shape(getattr(adapter, name)) if callable(getattr(adapter, name, None)) else None
    for adapter in (macos, windows, OSWorldDesktop)
    for name in SURFACE
}


@pytest.mark.parametrize("adapter", [macos, windows, OSWorldDesktop], ids=["macos", "windows", "osworld"])
@pytest.mark.parametrize("name", SURFACE)
def test_each_adapter_provides_the_desktop_surface(adapter, name):
    provided = PROVIDED[(adapter.__name__, name)]
    assert provided is not None, f"{adapter.__name__} lacks {name}"
    assert provided == shape(getattr(Desktop, name))


def test_the_surface_covers_what_the_callers_use():
    assert len(SURFACE) >= 20 and {"click_at", "recognize_text", "actionable_elements"} <= set(SURFACE)


@pytest.mark.skipif(sys.platform == "win32", reason="Windows picks windows.py")
def test_macos_is_the_adapter_off_windows():
    assert host is macos and current() is macos


def test_off_macos_a_host_without_the_mac_packages_has_no_desktop(monkeypatch):
    monkeypatch.setitem(sys.modules, "typesafe_computer_use.macos", None)  # as on Linux, where Quartz is absent
    monkeypatch.setattr(sys, "platform", "linux")
    picked = pick_host()
    assert isinstance(picked, NoDesktop)
    with pytest.raises(RuntimeError, match="no desktop to call click_at on: linux has no desktop adapter"):
        picked.click_at((1.0, 2.0))


def test_on_macos_a_missing_mac_package_is_an_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "typesafe_computer_use.macos", None)
    monkeypatch.setattr(sys, "platform", "darwin")
    with pytest.raises(ImportError):
        pick_host()


def fake_desktop() -> SimpleNamespace:
    return SimpleNamespace(frontmost_app_and_pid=lambda: ("Fake", 7), click_at=lambda point: None)


def test_using_swaps_the_adapter_for_the_block_and_restores_the_host():
    fake = fake_desktop()
    with using(fake) as swapped:
        assert swapped is fake and current() is fake
        assert desktop.frontmost_app_and_pid() == ("Fake", 7)
    assert current() is host


def test_using_restores_the_host_after_an_exception():
    with pytest.raises(RuntimeError, match="inside"), using(fake_desktop()):
        raise RuntimeError("inside")
    assert current() is host


def test_blocks_nest_and_unwind_in_order():
    outer, inner = fake_desktop(), fake_desktop()
    with using(outer):
        with using(inner):
            assert current() is inner
        assert current() is outer
    assert current() is host


def test_a_patch_through_desktop_inside_the_block_lands_on_the_fake(monkeypatch):
    fake = fake_desktop()
    fake_click_at, host_click_at = fake.click_at, host.click_at
    clicked = []
    with using(fake), monkeypatch.context() as patch:
        patch.setattr(desktop, "click_at", clicked.append)
        desktop.click_at((1.0, 2.0))
        assert fake.click_at == clicked.append
        assert host.click_at is host_click_at
    assert clicked == [(1.0, 2.0)]
    assert fake.click_at is fake_click_at, "the undo went to the fake, inside the block"
    assert host.click_at is host_click_at


def test_a_patch_through_desktop_outside_any_block_lands_on_the_host(monkeypatch):
    host_screenshot = host.screenshot
    with monkeypatch.context() as patch:
        patch.setattr(desktop, "screenshot", lambda: "patched")
        assert host.screenshot() == "patched"
    assert host.screenshot is host_screenshot


def test_deletes_go_to_the_adapter_in_use():
    fake = fake_desktop()
    with using(fake):
        del desktop.frontmost_app_and_pid
        with pytest.raises(AttributeError):
            desktop.frontmost_app_and_pid  # noqa: B018
    assert not hasattr(fake, "frontmost_app_and_pid")


def test_windows_presses_every_key_macos_presses():
    assert set(macos.KEYCODES) <= set(windows.VK)


# Chrome in full screen, as macOS listed its windows front to back: the toolbar window above the
# page's, then the menu bar copy. In points, on a 1470x956 display.
FULL_SCREEN_CHROME = [
    (0.0, 33.0, 1470.0, 158.0),  # the toolbar
    (0.0, 74.0, 1470.0, 81.0),
    (0.0, 155.0, 1470.0, 801.0),  # the page
    (0.0, 0.0, 1470.0, 33.0),
]


@pytest.fixture
def full_screen_chrome(monkeypatch):
    """Quartz lists FULL_SCREEN_CHROME for pid 7; accessibility's focused window is the whole display,
    unless the test takes it away. Nothing here reaches the machine."""
    listed = [
        {"kCGWindowOwnerPID": 7, "kCGWindowLayer": 0, "kCGWindowBounds": {"X": x, "Y": y, "Width": w, "Height": h}}
        for x, y, w, h in FULL_SCREEN_CHROME
    ]
    quartz = SimpleNamespace(
        kCGWindowListOptionOnScreenOnly=1,
        kCGWindowListExcludeDesktopElements=2,
        kCGNullWindowID=0,
        CGWindowListCopyWindowInfo=lambda options, window: listed,
    )
    focused = {"frame": (0.0, 0.0, 1470.0, 956.0)}
    ax = SimpleNamespace(
        AXUIElementCreateApplication=lambda pid: ("app", pid),
        AXUIElementSetMessagingTimeout=lambda element, seconds: 0,
        kAXFocusedWindowAttribute="AXFocusedWindow",
    )
    monkeypatch.setattr(macos, "Quartz", quartz)
    monkeypatch.setattr(macos, "AS", ax)
    monkeypatch.setattr(macos, "_ax_attr", lambda element, name: "window" if focused["frame"] else None)
    monkeypatch.setattr(macos, "_ax_frame", lambda element: focused["frame"])
    return focused


def test_full_screen_chrome_reads_the_focused_window_not_its_toolbar(full_screen_chrome):
    """Every Chrome run read 17% of the screen: the topmost window Quartz lists is the toolbar."""
    assert macos.frontmost_window_bounds(7) == (0.0, 0.0, 1470.0, 956.0)


def test_without_a_focused_window_the_topmost_quartz_window_stands_in(full_screen_chrome):
    full_screen_chrome["frame"] = None
    assert macos.frontmost_window_bounds(7) == FULL_SCREEN_CHROME[0]


def test_a_focused_window_too_small_to_work_in_is_passed_over(full_screen_chrome):
    full_screen_chrome["frame"] = (10.0, 10.0, 40.0, 300.0)
    assert macos.frontmost_window_bounds(7) == FULL_SCREEN_CHROME[0]


@pytest.mark.parametrize(
    ("attrs", "editor"),
    [
        ({"AXRole": "AXGroup", "AXEditableAncestor": "doc"}, True),  # a Google Doc's hidden key box
        ({"AXRole": "AXGroup", "AXDOMIdentifier": "docs-texteventtarget-descendant"}, True),  # the same, in Brave
        ({"AXRole": "AXGroup", "AXDOMIdentifier": "sidebar"}, False),  # another page's box, not editable
        ({"AXRole": "AXGroup"}, False),  # a focused panel, not editable
        ({"AXRole": "AXTextField", "AXEditableAncestor": "field"}, False),  # a form field already
    ],
)
def test_a_focused_element_inside_editable_page_content_is_an_editor(attrs, editor, monkeypatch):
    names = {"kAXFocusedUIElementAttribute": "AXFocusedUIElement", "kAXRoleAttribute": "AXRole"}
    ax = SimpleNamespace(AXUIElementCreateSystemWide=lambda: "system", **names)
    for name in ("Position", "Size", "Value", "Title", "Description", "PlaceholderValue"):
        setattr(ax, f"kAX{name}Attribute", f"AX{name}")
    monkeypatch.setattr(macos, "AS", ax)
    monkeypatch.setattr(macos, "_ax_attr", lambda element, name: "focused" if element == "system" else attrs.get(name))
    assert macos.focused_field().editor is editor


def keys_go_to(monkeypatch, pid: int | None, names: dict[int, str]) -> None:
    """Accessibility names the app with `pid` as the one the keyboard goes to, or none at all."""

    def running(pid):
        return SimpleNamespace(localizedName=lambda: names[pid])

    ax = SimpleNamespace(
        AXUIElementCreateSystemWide=lambda: "system",
        AXUIElementGetPid=lambda app, _: (0, pid),
        AXUIElementCopyAttributeValue=lambda element, name, _: (0, "focused app") if pid is not None else (-25204, None),
        kAXFocusedApplicationAttribute="AXFocusedApplication",
    )
    monkeypatch.setattr(macos, "AS", ax)
    monkeypatch.setattr(
        macos, "AppKit", SimpleNamespace(NSRunningApplication=SimpleNamespace(runningApplicationWithProcessIdentifier_=running))
    )


def test_the_keyboard_can_go_to_another_app_than_the_one_in_front(monkeypatch):
    keys_go_to(monkeypatch, 7, {7: "SystemOne"})
    assert KEYBOARD_FOCUS() == KeyboardFocus("SystemOne", 7)


def test_no_app_with_the_keyboard_is_said_with_the_error_that_said_so(monkeypatch):
    # Every Docs run from 16:32 on: -25204 at once, whichever app was in front.
    keys_go_to(monkeypatch, None, {})
    assert KEYBOARD_FOCUS() == KeyboardFocus("", None, "-25204")


def test_installed_browsers_are_the_known_ones_with_an_app_bundle(tmp_path, monkeypatch):
    (tmp_path / "Brave Browser.app").mkdir()
    (tmp_path / "Google Chrome.app").mkdir()
    (tmp_path / "Safari.app").mkdir()  # not a browser use_browser can drive
    monkeypatch.setattr(macos, "APP_FOLDERS", (tmp_path, tmp_path / "missing"))
    assert macos.installed_browsers() == ["Google Chrome", "Brave Browser"]


def test_installed_apps_are_every_bundle_but_the_browsers_sorted_by_name(tmp_path, monkeypatch):
    """'Open Photos' stopped at once: the run could reach a website and nothing else."""
    system, utilities = tmp_path / "System", tmp_path / "System" / "Utilities"
    utilities.mkdir(parents=True)
    for folder, name in [
        (system, "Photos.app"),
        (utilities, "Activity Monitor.app"),
        (tmp_path, "zoom.us.app"),
        (tmp_path, "Brave Browser.app"),  # use_browser reaches it
        (tmp_path, 'Odd "Quoted".app'),  # AppleScript could not quote it
        (tmp_path, "Notes.txt"),
    ]:
        (folder / name).mkdir()
    monkeypatch.setattr(macos, "APP_FOLDERS_ALL", (tmp_path, system, utilities, tmp_path / "missing"))
    assert macos.installed_apps() == ["Activity Monitor", "Photos", "zoom.us"]


def test_windows_and_the_osworld_vm_offer_no_apps_to_open():
    assert windows.installed_apps() == []
    assert OSWorldDesktop.installed_apps(None) == []


@pytest.mark.parametrize(
    "handler, browser",
    [
        ("/Applications/Brave Browser.app", "Brave Browser"),
        ("/Users/me/Applications/Arc.app", "Arc"),
        ("/Applications/Safari.app", None),  # not a browser use_browser can drive
        (None, None),
    ],
)
def test_the_default_browser_is_the_link_handler_when_use_browser_can_drive_it(handler, browser, monkeypatch):
    monkeypatch.setattr(macos, "_link_handler", lambda: handler)
    assert macos.default_browser() == browser


def test_the_frontmost_app_names_its_focused_element_when_the_system_cannot(monkeypatch):
    # Every run from 16:32 on: the system-wide question failed with -25204, Brave asked itself did not.
    names = {
        "kAXFocusedApplicationAttribute": "AXFocusedApplication",
        "kAXFocusedUIElementAttribute": "AXFocusedUIElement",
        "kAXRoleAttribute": "AXRole",
    }
    ax = SimpleNamespace(
        AXUIElementCreateSystemWide=lambda: "system",
        AXUIElementCreateApplication=lambda pid: f"app {pid}",
        AXUIElementSetMessagingTimeout=lambda element, seconds: 0,
        **names,
    )
    for name in ("Position", "Size", "Value", "Title", "Description", "PlaceholderValue"):
        setattr(ax, f"kAX{name}Attribute", f"AX{name}")
    answers = {
        ("app 42", "AXFocusedUIElement"): "key box",
        ("key box", "AXRole"): "AXGroup",
        ("key box", "AXEditableAncestor"): "document",
    }
    monkeypatch.setattr(macos, "AS", ax)
    monkeypatch.setattr(macos, "_ax_attr", lambda element, name: answers.get((element, name)))
    field = macos.focused_field(42)
    assert (field.role, field.editor, field.is_text) == ("AXGroup", True, True)
    assert macos.focused_field() is None  # without the frontmost app, there is no one else to ask

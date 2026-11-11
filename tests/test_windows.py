"""The Windows adapter's pure rules. Nothing here touches Windows, so it runs everywhere."""

import ctypes

import pytest

from typesafe_computer_use import windows
from typesafe_computer_use.models import ROLE_WORDS, TEXT_ROLES, Abort, Missed
from typesafe_computer_use.windows import (
    KEYEVENTF_EXTENDEDKEY,
    KEYEVENTF_KEYUP,
    KEYEVENTF_UNICODE,
    app_matches,
    display_name,
    key_events,
    landed,
    ocr_lines,
    pressable,
    role_for,
    unicode_events,
    wheel_delta,
)

# ------------------------------------------------------------------ roles


def test_control_types_map_onto_the_roles_the_shared_code_knows():
    assert role_for("ButtonControl") == "AXButton"
    assert role_for("HyperlinkControl") == "AXLink"
    assert role_for("EditControl") in TEXT_ROLES  # a focused edit box is a text field
    assert role_for("ComboBoxControl") in TEXT_ROLES
    assert role_for("TextControl") == "AXStaticText"  # where a list row's label is recovered from


def test_an_unknown_control_type_has_no_role():
    assert role_for("PaneControl") == ""
    assert role_for("") == ""


def test_every_mapped_control_role_has_a_word_or_is_structural():
    structural = {"AXGroup", "AXStaticText", "AXIncrementor"}
    assert {role for role in windows.CONTROL_TYPE_TO_ROLE.values()} - set(ROLE_WORDS) <= structural


# ------------------------------------------------------------------ what is pressable


def test_an_invoke_pattern_is_pressable():
    assert pressable(True, "")


def test_a_legacy_default_action_is_pressable():
    assert pressable(False, "Press")
    assert pressable(False, "Jump")


def test_the_legacy_pattern_alone_is_not_pressable():
    """Almost every element carries LegacyIAccessible; without a named action it is not a control."""
    assert not pressable(False, "")
    assert not pressable(False, "   ")


# ------------------------------------------------------------------ which window is the app


def test_an_app_matches_its_own_process_exactly():
    assert app_matches("notepad.exe", "Notepad.exe")
    assert app_matches("notepad", "notepad.exe")
    assert app_matches("OUTLOOK", "outlook.exe")


def test_a_browser_matches_by_its_product_name():
    assert app_matches("Google Chrome", "chrome.exe")
    assert app_matches("microsoft edge", "msedge.exe")


def test_no_substring_match():
    assert not app_matches("Outlook", "outlookhelper.exe")
    assert not app_matches("note", "notepad.exe")
    assert not app_matches("Google Chrome", "chromedriver.exe")


def test_a_chrome_tab_named_after_an_app_is_not_that_app():
    """The window title never counts: only the process that owns the window."""
    assert not app_matches("Outlook", "chrome.exe")


def test_a_browser_is_reported_by_its_product_name():
    assert display_name("chrome.exe") == "Google Chrome"
    assert display_name("msedge.exe") == "Microsoft Edge"
    assert display_name("notepad.exe") == "notepad.exe"
    assert app_matches(display_name("chrome.exe"), "chrome.exe")  # what is reported can be activated


# ------------------------------------------------------------------ input events


def test_a_plain_key_is_down_then_up():
    assert key_events("return") == [(0x0D, 0), (0x0D, KEYEVENTF_KEYUP)]


def test_command_becomes_control_held_around_the_key():
    assert key_events("a", command=True) == [(0x11, 0), (0x41, 0), (0x41, KEYEVENTF_KEYUP), (0x11, KEYEVENTF_KEYUP)]


def test_command_bracket_is_alt_left_the_windows_back():
    ext = KEYEVENTF_EXTENDEDKEY
    assert key_events("[", command=True) == [(0x12, 0), (0x25, ext), (0x25, ext | KEYEVENTF_KEYUP), (0x12, KEYEVENTF_KEYUP)]


def test_delete_is_an_extended_key():
    assert key_events("delete") == [(0x2E, KEYEVENTF_EXTENDEDKEY), (0x2E, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP)]


def test_the_arrows_and_the_page_keys_are_extended_keys():
    ext = KEYEVENTF_EXTENDEDKEY
    assert key_events("down") == [(0x28, ext), (0x28, ext | KEYEVENTF_KEYUP)]
    assert key_events("page_up") == [(0x21, ext), (0x21, ext | KEYEVENTF_KEYUP)]
    assert key_events("tab") == [(0x09, 0), (0x09, KEYEVENTF_KEYUP)]  # Tab is on the main block


def test_shift_is_held_around_a_key():
    assert key_events("return", shift=True) == [(0x10, 0), (0x0D, 0), (0x0D, KEYEVENTF_KEYUP), (0x10, KEYEVENTF_KEYUP)]


def test_text_is_typed_as_unicode_characters_not_keys():
    down, up = KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
    assert unicode_events("aé") == [(ord("a"), down), (ord("a"), up), (0xE9, down), (0xE9, up)]


def test_text_outside_ascii_survives():
    """pyautogui.typewrite dropped every one of these."""
    text = "Zoë, 東京, Ω"
    units = [unit for unit, flags in unicode_events(text) if not flags & KEYEVENTF_KEYUP]
    assert "".join(map(chr, units)) == text


def test_a_character_outside_the_bmp_is_a_surrogate_pair():
    units = [unit for unit, flags in unicode_events("😀") if not flags & KEYEVENTF_KEYUP]
    assert units == [0xD83D, 0xDE00]


def test_the_scroll_the_actions_ask_for_is_whole_notches_in_the_macos_direction():
    assert wheel_delta(10) > 0 and wheel_delta(-10) < 0  # positive scrolls up on both
    assert wheel_delta(-10) == -400  # ten lines at three a notch
    assert wheel_delta(3) == windows.WHEEL_DELTA


def test_the_input_record_has_the_size_windows_expects():
    """SendInput rejects a record of the wrong size, so the union must be as wide as MOUSEINPUT."""
    pointer = ctypes.sizeof(ctypes.c_void_p)
    assert ctypes.sizeof(windows._Input) == (40 if pointer == 8 else 28)


# ------------------------------------------------------------------ a click that reads back


def test_a_click_lands_only_where_the_cursor_went():
    assert landed((100, 200), (100.0, 200.0))
    assert landed((100, 200), (101.0, 199.0))
    assert not landed((100, 200), (0.0, 0.0))  # another desktop has the input
    assert not landed((100, 200), (100.0, 260.0))


def test_a_click_that_did_not_land_presses_nothing(monkeypatch):
    sent = []
    monkeypatch.setattr(windows, "_move", lambda point: None)
    monkeypatch.setattr(windows, "mouse_location", lambda: (300.0, 300.0))
    monkeypatch.setattr(windows, "_send", sent.append)
    with pytest.raises(Missed, match="not \\(640, 480\\)"):
        windows.click_at((640.0, 480.0))
    assert sent == []


def test_a_click_that_landed_presses_and_releases(monkeypatch):
    sent = []
    monkeypatch.setattr(windows, "_move", lambda point: None)
    monkeypatch.setattr(windows, "mouse_location", lambda: (640.0, 480.0))
    monkeypatch.setattr(windows, "_send", sent.append)
    windows.click_at((640.4, 479.6))
    assert [event.u.mi.dwFlags for event in sent] == [windows.MOUSEEVENTF_LEFTDOWN, windows.MOUSEEVENTF_LEFTUP]


def windows_input(monkeypatch, cursor=lambda: (640.0, 480.0)):
    """The adapter's input with the machine replaced: every event sent, every cursor move, in order."""
    log = []
    monkeypatch.setattr(windows, "_move", lambda point: log.append(("move", point)))
    monkeypatch.setattr(windows, "mouse_location", cursor)
    monkeypatch.setattr(windows, "_send", lambda event: log.append(("send", event.u.mi.dwFlags)))
    monkeypatch.setattr(windows, "sleep_watching", lambda seconds: None)
    return log


def test_a_right_click_presses_and_releases_the_right_button(monkeypatch):
    log = windows_input(monkeypatch)
    windows.click_at((640.0, 480.0), button="right")
    assert log[1:] == [("send", windows.MOUSEEVENTF_RIGHTDOWN), ("send", windows.MOUSEEVENTF_RIGHTUP)]


def test_a_double_click_is_two_presses_in_a_row(monkeypatch):
    log = windows_input(monkeypatch)
    windows.click_at((640.0, 480.0), count=2)
    assert [event for kind, event in log if kind == "send"] == [windows.MOUSEEVENTF_LEFTDOWN, windows.MOUSEEVENTF_LEFTUP] * 2


@pytest.mark.parametrize("button, count", [("middle", 1), ("left", 0), ("left", 4)])
def test_a_click_that_is_no_click_is_refused_before_the_cursor_moves(monkeypatch, button, count):
    log = windows_input(monkeypatch)
    with pytest.raises(ValueError, match="cannot click"):
        windows.click_at((640.0, 480.0), button=button, count=count)
    assert log == []


def test_a_drag_holds_the_button_through_the_moves_and_lets_go_at_the_end(monkeypatch):
    log = windows_input(monkeypatch, cursor=lambda: (100.0, 100.0))
    windows.drag((100.0, 100.0), (400.0, 220.0))
    moves = [point for kind, point in log if kind == "move"]
    sends = [event for kind, event in log if kind == "send"]
    assert sends == [windows.MOUSEEVENTF_LEFTDOWN, windows.MOUSEEVENTF_LEFTUP]
    assert (
        moves[0] == (100, 100) and moves[-1] == (400, 220) and len(moves) == windows.DRAG_STEPS + 2
    )  # reach, steps, release point
    assert log.index(("send", windows.MOUSEEVENTF_LEFTDOWN)) == 1 and log[-1] == ("send", windows.MOUSEEVENTF_LEFTUP)
    assert log[-2] == ("move", (400, 220))  # the button comes up at the cursor's place, which the up event does not carry


def test_a_drag_that_never_reached_its_start_presses_nothing(monkeypatch):
    log = windows_input(monkeypatch, cursor=lambda: (300.0, 300.0))
    with pytest.raises(Missed):
        windows.drag((100.0, 100.0), (400.0, 220.0))
    assert [kind for kind, _ in log] == ["move"]


def test_an_interrupted_drag_still_lets_go_of_the_button(monkeypatch):
    log = windows_input(monkeypatch, cursor=lambda: (100.0, 100.0))
    looks = []

    def check_abort():
        looks.append(1)
        if len(looks) > 3:
            raise KeyboardInterrupt

    monkeypatch.setattr(windows, "check_abort", check_abort)
    with pytest.raises(KeyboardInterrupt):
        windows.drag((100.0, 100.0), (400.0, 220.0))
    assert log[-1] == ("send", windows.MOUSEEVENTF_LEFTUP)
    assert sum(kind == "move" for kind, _ in log) < windows.DRAG_STEPS + 1  # it stopped on the way
    assert log[-2] == ("move", (100, 100))  # and went back to where the item was taken before it let go


def test_the_abort_corner_half_way_through_a_drag_lets_go_at_the_start_not_in_the_corner(monkeypatch):
    log = windows_input(monkeypatch)
    monkeypatch.setattr(
        windows, "mouse_location", lambda: (0.0, 0.0) if sum(kind == "move" for kind, _ in log) >= 4 else (100.0, 100.0)
    )
    with pytest.raises(Abort):
        windows.drag((100.0, 100.0), (400.0, 220.0))
    assert log[-2:] == [("move", (100, 100)), ("send", windows.MOUSEEVENTF_LEFTUP)]


def test_the_corner_stops_a_drag_before_the_cursor_moves(monkeypatch):
    log = windows_input(monkeypatch, cursor=lambda: (0.0, 0.0))
    with pytest.raises(Abort):
        windows.drag((100.0, 100.0), (400.0, 220.0))
    assert log == []


def test_the_abort_corner_stops_a_double_click_between_its_two_clicks(monkeypatch):
    log = windows_input(monkeypatch)
    monkeypatch.setattr(windows, "mouse_location", lambda: (0.0, 0.0) if len(log) >= 3 else (640.0, 480.0))
    with pytest.raises(Abort):
        windows.click_at((640.0, 480.0), count=2)
    assert [event for kind, event in log if kind == "send"] == [windows.MOUSEEVENTF_LEFTDOWN, windows.MOUSEEVENTF_LEFTUP]


def test_a_press_that_fails_part_way_lets_go_of_the_keys_it_holds(monkeypatch):
    sent = []

    def send(event):
        sent.append((event.u.ki.wVk, event.u.ki.dwFlags))
        if len(sent) == 2:  # the key itself, after Ctrl is down
            raise OSError("the input desktop is locked")

    monkeypatch.setattr(windows, "_send", send)
    with pytest.raises(OSError):
        windows.press("c", command=True)
    assert sent[0] == (0x11, 0) and sent[-1] == (0x11, KEYEVENTF_KEYUP)  # Ctrl went down, and is up again after the failure


def test_a_release_that_fails_does_not_leave_the_other_keys_held_or_hide_the_first_error(monkeypatch):
    sent = []

    def send(event):
        sent.append((event.u.ki.wVk, event.u.ki.dwFlags))
        if len(sent) == 3:  # Ctrl and Shift are down, the key itself fails
            raise OSError("the input desktop is locked")
        if event.u.ki.dwFlags & KEYEVENTF_KEYUP and event.u.ki.wVk == 0x10:
            raise OSError("and the release of Shift fails too")

    monkeypatch.setattr(windows, "_send", send)
    with pytest.raises(OSError, match="the input desktop is locked"):
        windows.press("c", command=True, shift=True)
    ups = [vk for vk, flags in sent if flags & KEYEVENTF_KEYUP]
    assert 0x11 in ups and 0x10 in ups  # both were tried, in reverse, whatever happened to one of them


def test_the_abort_corner_stops_a_click_before_the_cursor_moves(monkeypatch):
    log = windows_input(monkeypatch, cursor=lambda: (0.0, 0.0))
    with pytest.raises(Abort):
        windows.click_at((640.0, 480.0))
    assert log == []


def test_a_command_chord_cannot_also_hold_option_or_control():
    assert key_events("[", command=True, shift=True)[0] == (0x10, 0)
    with pytest.raises(ValueError, match="cannot also hold"):
        key_events("[", command=True, option=True)


def test_control_and_option_are_held_around_a_key():
    ctrl, alt = 0x11, 0x12
    assert key_events("tab", control=True) == [(ctrl, 0), (0x09, 0), (0x09, KEYEVENTF_KEYUP), (ctrl, KEYEVENTF_KEYUP)]
    assert key_events("tab", control=True, shift=True)[:3] == [(0x10, 0), (ctrl, 0), (0x09, 0)]
    assert key_events("z", option=True)[:2] == [(alt, 0), (0x5A, 0)]


def test_command_and_control_are_the_one_control_key_on_windows():
    assert key_events("c", command=True, control=True) == key_events("c", command=True) == key_events("c", control=True)


# ------------------------------------------------------------------ OCR


def test_ocr_lines_box_the_words_and_report_full_confidence():
    result = {
        "text": "Sign in",
        "lines": [
            {
                "text": "Sign in",
                "words": [
                    {"text": "Sign", "bounding_rect": {"x": 10, "y": 20, "width": 30, "height": 12}},
                    {"text": "in", "bounding_rect": {"x": 45, "y": 18, "width": 12, "height": 16}},
                ],
            },
            {"text": "", "words": []},
        ],
    }
    assert ocr_lines(result) == [("Sign in", windows.OCR_CONFIDENCE, (10.0, 18.0, 57.0, 34.0))]
    assert windows.OCR_CONFIDENCE == 1.0  # Windows.Media.Ocr reports none

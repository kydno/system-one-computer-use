"""Exercise the real input adapter with OS calls replaced; no synthetic input reaches the host."""

from types import SimpleNamespace

import pytest

from typesafe_computer_use import actions, macos
from typesafe_computer_use.models import Abort


@pytest.fixture
def input_events(monkeypatch):
    events = []
    quartz = SimpleNamespace(
        kCGEventMouseMoved="move",
        kCGEventLeftMouseDown="down",
        kCGEventLeftMouseUp="up",
        kCGMouseButtonLeft=0,
        CGEventCreateMouseEvent=lambda _, kind, point, button: (kind, point),
        CGEventCreateKeyboardEvent=lambda _, code, down: {"down": down},
        CGEventKeyboardSetUnicodeString=lambda event, length, text: event.update(text=text),
        kCGEventFlagMaskCommand="command",
        CGEventSetFlags=lambda event, flags: event.update(flags=flags),
        kCGScrollEventUnitLine="line",
        CGEventCreateScrollWheelEvent=lambda _, unit, count, lines: ("scroll", lines),
    )
    monkeypatch.setattr(macos, "Quartz", quartz)
    monkeypatch.setattr(macos, "_post", events.append)
    return events


def test_corner_abort_prevents_the_click_from_moving_the_pointer(input_events, monkeypatch):
    monkeypatch.setattr(macos, "mouse_location", lambda: (0, 0))
    with pytest.raises(Abort):
        macos.click_at((200, 200))
    assert input_events == []


def test_typing_checks_abort_between_characters_and_releases_the_key(input_events, monkeypatch):
    monkeypatch.setattr(macos, "mouse_location", lambda: (0, 0) if input_events else (500, 500))
    with pytest.raises(Abort):
        macos.type_text("abc")
    assert input_events == [{"down": True, "text": "a", "flags": 0}, {"down": False, "text": "a", "flags": 0}]


def test_typed_text_after_select_all_carries_no_command(input_events):
    # A sourceless event inherits the Command that Cmd+A left held, and "Barcelona"'s n opened a new window.
    macos.clear_field()
    macos.type_text("Barcelona")

    select_all, delete, typed = input_events[:2], input_events[2:4], input_events[4:]
    assert [event["flags"] for event in select_all + delete] == ["command", "command", 0, 0]
    assert "".join(event["text"] for event in typed if event["down"]) == "Barcelona"
    assert all(event["flags"] == 0 for event in typed)


def test_a_line_break_is_typed_as_the_return_key(input_events, monkeypatch):
    pressed = []
    monkeypatch.setattr(macos, "press", lambda key, command=False: pressed.append(key))
    macos.type_text("a\nb")
    assert pressed == ["return"]
    assert [event["text"] for event in input_events if event["down"]] == ["a", "b"]


def test_click_releases_the_button_when_interrupted_after_mouse_down(input_events, monkeypatch):
    def post(event):
        input_events.append(event)
        if event[0] == "down":
            raise KeyboardInterrupt

    monkeypatch.setattr(macos, "_post", post)
    with pytest.raises(KeyboardInterrupt):
        macos.click_at((200, 200))
    assert [event[0] for event in input_events] == ["move", "down", "up"]


def test_a_key_goes_back_up_when_interrupted_after_key_down(input_events, monkeypatch):
    def post(event):
        input_events.append(dict(event))
        if event["down"]:
            raise KeyboardInterrupt

    monkeypatch.setattr(macos, "_post", post)
    with pytest.raises(KeyboardInterrupt):
        macos.press("a", command=True)
    assert input_events == [{"down": True, "flags": "command"}, {"down": False, "flags": "command"}]


def test_corner_abort_stops_a_scroll_before_the_pointer_is_parked(input_events, monkeypatch):
    monkeypatch.setattr(macos, "frontmost_window_center", lambda: (300.0, 300.0))
    monkeypatch.setattr(macos, "mouse_location", lambda: (0, 0))
    with pytest.raises(Abort):
        macos.scroll(-10)
    assert input_events == []


def test_a_scroll_parks_the_pointer_at_the_point_it_was_given(input_events, monkeypatch):
    monkeypatch.setattr(macos, "frontmost_window_center", lambda: pytest.fail("a point was given"))
    monkeypatch.setattr(macos, "mouse_location", lambda: (500, 500))
    macos.scroll(-10, (175.0, 590.0))
    assert input_events == [("move", (175.0, 590.0)), ("scroll", -10)]


def test_a_scroll_with_no_point_parks_the_pointer_over_the_window_center(input_events, monkeypatch):
    monkeypatch.setattr(macos, "frontmost_window_center", lambda: (300.0, 300.0))
    monkeypatch.setattr(macos, "mouse_location", lambda: (500, 500))
    macos.scroll(10)
    assert input_events == [("move", (300.0, 300.0)), ("scroll", 10)]


@pytest.mark.parametrize(
    "action", [lambda: macos.open_url("Google Chrome", "https://example.com"), lambda: macos.activate("Finder")]
)
def test_corner_abort_stops_an_app_switch_before_any_applescript(action, monkeypatch):
    monkeypatch.setattr(macos, "mouse_location", lambda: (0, 0))
    with pytest.raises(Abort):
        action()


def test_pending_abort_after_a_decision_prevents_dispatch(screen, monkeypatch):
    monkeypatch.setattr(macos, "mouse_location", lambda: (0, 0))
    monkeypatch.setattr(macos, "press", lambda *a: pytest.fail("must not submit after abort"))
    with pytest.raises(Abort):
        actions.perform(SimpleNamespace(chosen="press_enter"), screen, [], None)


@pytest.mark.parametrize(
    "action", [lambda: macos.ax_press(object()), lambda: macos.ax_focus(object()), lambda: macos.ax_set_value(object(), "text")]
)
def test_accessibility_helpers_do_not_swallow_abort(action, monkeypatch):
    monkeypatch.setattr(macos, "mouse_location", lambda: (0, 0))
    with pytest.raises(Abort):
        action()

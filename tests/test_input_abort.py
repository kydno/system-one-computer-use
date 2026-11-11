"""Exercise the real input adapter with OS calls replaced; no synthetic input reaches the host."""

from types import SimpleNamespace

import pytest

from typesafe_computer_use import actions, macos
from typesafe_computer_use.models import Abort

COMMAND, SHIFT, OPTION, CONTROL = 0x100000, 0x20000, 0x80000, 0x40000  # Quartz's own flag masks


@pytest.fixture
def input_events(monkeypatch):
    events = []
    quartz = SimpleNamespace(
        kCGEventMouseMoved="move",
        kCGEventLeftMouseDown="down",
        kCGEventLeftMouseUp="up",
        kCGEventLeftMouseDragged="drag",
        kCGEventRightMouseDown="right down",
        kCGEventRightMouseUp="right up",
        kCGMouseButtonLeft=0,
        kCGMouseButtonRight=1,
        kCGMouseEventClickState="click state",
        CGEventCreateMouseEvent=lambda _, kind, point, button: (kind, point),
        CGEventSetIntegerValueField=lambda event, field, value: events.append(("click", value)),
        CGEventCreateKeyboardEvent=lambda _, code, down: {"down": down},
        CGEventKeyboardSetUnicodeString=lambda event, length, text: event.update(text=text),
        kCGEventFlagMaskCommand=COMMAND,
        kCGEventFlagMaskShift=SHIFT,
        kCGEventFlagMaskAlternate=OPTION,
        kCGEventFlagMaskControl=CONTROL,
        CGEventSetFlags=lambda event, flags: event.update(flags=flags),
        kCGScrollEventUnitLine="line",
        CGEventCreateScrollWheelEvent=lambda _, unit, count, lines: ("scroll", lines),
    )
    monkeypatch.setattr(macos, "Quartz", quartz)
    monkeypatch.setattr(macos, "_post", events.append)
    monkeypatch.setattr(macos, "sleep_watching", lambda seconds: None)
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
    assert [event["flags"] for event in select_all + delete] == [COMMAND, COMMAND, 0, 0]
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
    assert input_events == [{"down": True, "flags": COMMAND}, {"down": False, "flags": COMMAND}]


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


def test_a_hover_parks_the_pointer_and_presses_nothing(input_events, monkeypatch):
    monkeypatch.setattr(macos, "mouse_location", lambda: (500, 500))
    macos.hover((175.0, 590.0))
    assert input_events == [("move", (175.0, 590.0))]


def test_corner_abort_stops_a_hover_before_the_pointer_moves(input_events, monkeypatch):
    monkeypatch.setattr(macos, "mouse_location", lambda: (0, 0))
    with pytest.raises(Abort):
        macos.hover((175.0, 590.0))
    assert input_events == []


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


def activating(monkeypatch, windows: list) -> list[str]:
    """macos.activate against an app that is frontmost at once and shows `windows` in turn."""
    scripts: list[str] = []
    monkeypatch.setattr(macos, "osascript", lambda script: scripts.append(script) or "")
    monkeypatch.setattr(macos, "frontmost_app_and_pid", lambda: ("Claude", 42))
    monkeypatch.setattr(macos, "frontmost_window_bounds", lambda pid=None: windows.pop(0) if len(windows) > 1 else windows[0])
    monkeypatch.setattr(macos.time, "sleep", lambda s: None)
    return scripts


def test_an_app_brought_to_the_front_is_asked_for_a_window_as_a_dock_click_does(monkeypatch):
    scripts = activating(monkeypatch, [None, (0.0, 0.0, 800.0, 600.0)])
    assert macos.activate("Claude") is True
    assert scripts == ['tell application "Claude"\nreopen\nactivate\nend tell']


def test_an_app_in_front_with_no_window_on_screen_is_not_activated(monkeypatch):
    activating(monkeypatch, [None])
    assert macos.activate("Claude", timeout=0.05) is False


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


AT, TO = (200.0, 200.0), (400.0, 260.0)


def test_a_right_click_posts_the_right_button_and_a_plain_click_posts_no_click_count(input_events):
    macos.click_at(AT, button="right")
    macos.click_at(AT)
    assert input_events == [("move", AT), ("right down", AT), ("right up", AT), ("move", AT), ("down", AT), ("up", AT)]


@pytest.mark.parametrize("count", [2, 3])
def test_repeated_clicks_each_carry_their_number_so_an_app_reads_a_double_click(input_events, count):
    macos.click_at(AT, count=count)
    pairs = [(("click", n), ("down", AT), ("click", n), ("up", AT)) for n in range(1, count + 1)]
    assert input_events == [("move", AT), *(event for pair in pairs for event in pair)]


@pytest.mark.parametrize("button, count", [("middle", 1), ("left", 0), ("left", 4)])
def test_a_click_that_is_no_click_is_refused_before_anything_is_posted(input_events, button, count):
    with pytest.raises(ValueError, match="cannot click"):
        macos.click_at(AT, button=button, count=count)
    assert input_events == []


def test_the_abort_corner_stops_a_double_click_between_its_two_clicks(input_events, monkeypatch):
    monkeypatch.setattr(macos, "mouse_location", lambda: (0, 0) if len(input_events) > 4 else (500, 500))
    with pytest.raises(Abort):
        macos.click_at(AT, count=2)
    assert [e for e in input_events if e[0] in ("down", "up")] == [("down", AT), ("up", AT)]  # the first click finished


def test_a_drag_presses_moves_in_steps_and_releases_at_the_end(input_events):
    macos.drag(AT, TO)
    kinds = [event[0] for event in input_events]
    assert kinds == ["move", "down", *["drag"] * macos.DRAG_STEPS, "up"]
    assert input_events[1][1] == AT and input_events[-1][1] == pytest.approx(TO)
    xs = [event[1][0] for event in input_events[2:-1]]
    assert xs == sorted(xs) and xs[0] > AT[0]  # on its way, never jumping


def test_a_drag_interrupted_after_the_press_releases_the_button_where_it_was(input_events, monkeypatch):
    def post(event):
        input_events.append(event)
        if event[0] == "down":
            raise KeyboardInterrupt

    monkeypatch.setattr(macos, "_post", post)
    with pytest.raises(KeyboardInterrupt):
        macos.drag(AT, TO)
    assert [event[0] for event in input_events] == ["move", "down", "up"] and input_events[-1][1] == AT


def test_the_abort_corner_half_way_through_a_drag_lets_go_where_the_pointer_got_to(input_events, monkeypatch):
    monkeypatch.setattr(macos, "mouse_location", lambda: (0, 0) if sum(e[0] == "drag" for e in input_events) >= 3 else (500, 500))
    with pytest.raises(Abort):
        macos.drag(AT, TO)
    kinds = [event[0] for event in input_events]
    assert kinds == ["move", "down", "drag", "drag", "drag", "up"]
    assert input_events[-1][1] == input_events[-2][1] != TO  # dropped where it stopped, not where it was headed


def test_the_corner_stops_a_drag_before_the_pointer_moves(input_events, monkeypatch):
    monkeypatch.setattr(macos, "mouse_location", lambda: (0, 0))
    with pytest.raises(Abort):
        macos.drag(AT, TO)
    assert input_events == []


@pytest.mark.parametrize(
    "held, mask",
    [
        ({}, 0),
        ({"command": True}, COMMAND),
        ({"command": True, "shift": True}, COMMAND | SHIFT),
        ({"control": True}, CONTROL),
        ({"control": True, "shift": True}, CONTROL | SHIFT),
        ({"option": True, "command": True}, OPTION | COMMAND),
    ],
)
def test_a_key_carries_exactly_the_modifiers_it_was_given(input_events, held, mask):
    macos.press("tab", **held)
    assert [event["flags"] for event in input_events] == [mask, mask]

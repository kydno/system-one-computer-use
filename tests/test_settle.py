from types import SimpleNamespace

import pytest
from PIL import Image

from typesafe_computer_use import actions, runner
from typesafe_computer_use.actions import Look
from typesafe_computer_use.models import Screen
from typesafe_computer_use.platform_adapter import desktop

SIZE = (2000, 1200)


def frame(shade: int = 0, clock: int = 0) -> Image.Image:
    """A capture: a page band in `shade`, and a menu bar clock in `clock`."""
    image = Image.new("RGB", SIZE)
    image.paste((shade,) * 3, (0, 400, SIZE[0], 800))
    image.paste((clock,) * 3, (1800, 0, 2000, 60))
    return image


BEFORE = Screen(image=frame(), scale=2.0, app="Brave Browser", field=None, url="https://www.google.com/travel/flights")


def watch(monkeypatch, frames: list[Image.Image]) -> dict:
    """A clock that only the waits move, and a display that shows `frames` in turn, then the last."""
    seen = {"now": 0.0, "looks": 0}
    monkeypatch.setattr(runner.time, "monotonic", lambda: seen["now"])
    monkeypatch.setattr(desktop, "sleep_watching", lambda seconds: seen.update(now=seen["now"] + seconds))

    def screenshot():
        seen["looks"] += 1
        return frames[min(seen["looks"], len(frames)) - 1]

    monkeypatch.setattr(desktop, "screenshot", screenshot)
    return seen


def test_a_screen_that_changed_and_then_held_still_has_settled(monkeypatch):
    seen = watch(monkeypatch, [frame(120), frame(120)])
    runner.settle(BEFORE, 2.0)
    assert seen["looks"] == 2 and seen["now"] == 2 * runner.SETTLE_LOOK


def test_a_screen_still_repainting_is_watched_until_it_holds(monkeypatch):
    seen = watch(monkeypatch, [frame(40), frame(80), frame(120), frame(120)])
    runner.settle(BEFORE, 2.0)
    assert seen["looks"] == 4


def test_a_screen_that_has_not_changed_yet_gets_the_whole_limit(monkeypatch):
    """The click may be waiting on the network: an unchanged screen is no proof it is done."""
    seen = watch(monkeypatch, [frame()])
    runner.settle(BEFORE, 2.0)
    assert seen["now"] == 2.0


def test_a_ticking_clock_is_not_a_change(monkeypatch):
    seen = watch(monkeypatch, [frame(clock=200), frame(clock=255)])
    runner.settle(BEFORE, 2.0)
    assert seen["now"] == 2.0


def test_a_screen_that_never_holds_still_gets_the_whole_limit(monkeypatch):
    seen = watch(monkeypatch, [frame(40 * (n % 5 + 1)) for n in range(20)])
    runner.settle(BEFORE, 2.0)
    assert seen["now"] == 2.0


def test_no_limit_means_no_looks(monkeypatch):
    seen = watch(monkeypatch, [frame(120)])
    runner.settle(BEFORE, 0)
    assert seen["looks"] == 0 and seen["now"] == 0.0


# What `settle_action` does with what the action's own check saw (issue 16).

FULL = runner.DEFAULT_DELAY


def test_a_look_the_check_took_counts_as_the_first_one(monkeypatch):
    """A scroll's check saw the list move; a screen still that way one look later has settled."""
    seen = watch(monkeypatch, [frame(120)])
    runner.settle_action(BEFORE, FULL, "scroll_down", "scrolled down", Look(frame(120), changed=True))
    assert seen["looks"] == 1 and seen["now"] == runner.SETTLE_LOOK


def test_a_look_that_is_still_moving_is_watched_as_before(monkeypatch):
    seen = watch(monkeypatch, [frame(80), frame(120), frame(120)])
    runner.settle(BEFORE, FULL, seen=frame(40))
    assert seen["looks"] == 3


def test_a_scroll_its_check_saw_change_nothing_does_not_settle(monkeypatch):
    """A list at its end stays as it is: there is nothing to wait for."""
    seen = watch(monkeypatch, [frame()])
    runner.settle_action(BEFORE, FULL, "scroll_down", "scrolled down (nothing there moved)", Look(frame(), changed=False))
    assert seen["looks"] == 0 and seen["now"] == 0.0


def test_a_wait_does_not_settle_again(monkeypatch):
    """The wait itself slept `actions.WAIT_SECONDS`."""
    seen = watch(monkeypatch, [frame()])
    runner.settle_action(BEFORE, FULL, "wait", "waited", None)
    assert seen["looks"] == 0


@pytest.mark.parametrize(
    "kind, what",
    [
        ("use_browser", "use_browser refused: the writer proposed no usable URL for this goal"),
        ("click_item", "click refused: 'Buy' was not clicked, it is off screen"),
    ],
)
def test_a_refusal_did_nothing_and_does_not_settle(monkeypatch, kind, what):
    seen = watch(monkeypatch, [frame()])
    runner.settle_action(BEFORE, FULL, kind, what, None)
    assert seen["looks"] == 0


def test_a_refusal_after_closing_a_popup_still_settles(monkeypatch):
    """Closing the popup changed the screen, though the click after it was refused."""
    seen = watch(monkeypatch, [frame(120), frame(120)])
    runner.settle_action(BEFORE, FULL, "click_item", "closed Cookies then click refused: 'Buy' was not clicked, gone", None)
    assert seen["looks"] == 2


def test_a_press_that_showed_nothing_then_a_click_gets_the_whole_limit(monkeypatch):
    """The press's check saw no change, but the pointer click after it is a new action nobody looked at:
    it may be waiting on the network."""
    seen = watch(monkeypatch, [frame()])
    what = "clicked 'Return' (after an accessibility press that showed nothing)"
    runner.settle_action(BEFORE, FULL, "click_item", what, None)
    assert seen["now"] == FULL


def test_a_scroll_waits_at_most_its_own_cap(monkeypatch):
    seen = watch(monkeypatch, [frame(40 * (n % 5 + 1)) for n in range(20)])
    runner.settle_action(BEFORE, FULL, "scroll_down", "scrolled down", Look(frame(200), changed=True))
    assert seen["now"] == runner.SETTLE_CAPS["scroll_down"]


def test_a_click_keeps_the_whole_limit(monkeypatch):
    """A click may start a page load, so its settle is not cut short."""
    seen = watch(monkeypatch, [frame(40 * (n % 5 + 1)) for n in range(20)])
    runner.settle_action(BEFORE, FULL, "click_item", "pressed 'Search' via accessibility", Look(frame(200), changed=True))
    assert seen["now"] == FULL


@pytest.mark.parametrize("limit", [1.0, 0])
def test_a_shorter_delay_than_the_cap_wins(monkeypatch, limit):
    """`--delay 0` still means no looks, as on OSWorld."""
    seen = watch(monkeypatch, [frame(40 * (n % 5 + 1)) for n in range(20)])
    runner.settle_action(BEFORE, limit, "scroll_down", "scrolled down", Look(frame(200), changed=True))
    assert seen["now"] == limit and (limit or seen["looks"] == 0)


# Where the looks come from: the checks keep them, and an action reads only its own.


def test_a_press_that_showed_keeps_its_look(monkeypatch):
    shown = frame(120)
    monkeypatch.setattr(desktop, "sleep_watching", lambda seconds: None)
    monkeypatch.setattr(desktop, "screenshot", lambda: shown)
    assert actions.press_showed(BEFORE)
    assert actions.last_look() == Look(shown, changed=True)
    assert actions.last_look() is None  # read once


def test_a_press_that_showed_nothing_keeps_no_look(monkeypatch):
    """A pointer click follows it, so its look says nothing about the click."""
    monkeypatch.setattr(desktop, "sleep_watching", lambda seconds: None)
    monkeypatch.setattr(desktop, "screenshot", lambda: frame())
    assert not actions.press_showed(BEFORE)
    assert actions.last_look() is None


def test_a_look_from_an_earlier_action_is_not_the_next_ones(monkeypatch):
    """An escape takes no look; the look a scroll before it left must not seed its settle."""
    actions.looked(frame(120), changed=False)
    monkeypatch.setattr(desktop, "press", lambda name, command=False: None)
    what = actions.perform(SimpleNamespace(chosen="press_escape"), BEFORE, [], None)
    assert what == "pressed Escape" and actions.last_look() is None

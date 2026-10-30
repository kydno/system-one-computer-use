from PIL import Image

from typesafe_computer_use import runner
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

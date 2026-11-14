"""`handoff.json`: the story a run that stopped short of the goal leaves for an outer agent.

Each scenario drives the real loop (see world.py) to one of the ways a run ends unachieved and reads
the packet back from the run folder; an achieved run and a dry run leave none. The pages are made up.
"""

from __future__ import annotations

import io
import json

from world import FakeWriter, Page, World, drive, scripted

from typesafe_computer_use import runner
from typesafe_computer_use.events import Events
from typesafe_computer_use.runner import EARLIER_LINES, HANDOFF_FILE, HANDOFF_RAW, MAX_STALLS, STOPPED

GOAL = "buy a ticket to the next show"
HOME = "https://example.com/"
TICKETS = "https://example.com/tickets"
FORMS = "https://example.com/forms"
NOT_YET = {"achieved": False, "answer": "Not there yet."}

PACKET_KEYS = {
    "goal",
    "outcome",
    "why",
    "answer",
    "last_focus",
    "actions",
    "handoffs",
    "questions",
    "earlier_screens",
    "current_screen",
    "moves",
    "plan",
    "read_only",
    "permissions",
}


def packet(tmp_path) -> dict:
    return json.loads((tmp_path / "run" / HANDOFF_FILE).read_text())


def handed_on(state, tmp_path) -> dict:
    """The packet, checked for what every packet holds, whatever the stop."""
    p = packet(tmp_path)
    assert set(p) == PACKET_KEYS
    assert p["goal"] == GOAL
    assert p["outcome"] == state.outcome and p["why"] == STOPPED[state.outcome]
    assert p["answer"] == state.answer.text
    # One entry per action, each paired with the screen it was taken on.
    assert len(state.seen) == len(state.history) == len(p["actions"])
    assert [a["action"] for a in p["actions"]] == state.history
    for a in p["actions"]:
        assert set(a) == {"action", "app", "url", "then"}
        assert a["then"] is None or set(a["then"]) == {"app", "url", "changed_screen"}
    assert set(p["current_screen"]) == {"app", "url", "field", "text", "raw"}
    assert (tmp_path / "run" / p["current_screen"]["raw"]).is_file()
    assert sum(len(s["text"]) for s in p["earlier_screens"]) <= EARLIER_LINES
    assert "click_item" in p["moves"] and "done" not in p["moves"] and "none" not in p["moves"]
    run = json.loads((tmp_path / "run" / "run.json").read_text())
    assert run["handoff"] == HANDOFF_FILE and run["goal_achieved"] is False
    return p


def tickets() -> World:
    return World(
        [
            Page(name="home", items=["Home", "Tickets", "About"], url=HOME, on={"click:Tickets": "tickets"}),
            Page(name="tickets", items=["Next show", "Buy", "Terms"], url=TICKETS),
        ]
    )


def test_a_stuck_run_hands_on_every_action_the_focuses_and_the_screen_it_ended_on(monkeypatch, tmp_path):
    world = World(
        [
            Page(name="forms", items=["Agency", "-Any-", "Apply Filters"], url=FORMS, on={"click:-Any-": "open"}),
            Page(name="open", items=["Civil Division", "Tax Division"], url=FORMS),
        ]
    )
    writer = FakeWriter(reviews=[{"focus": "Open the '-Any-' dropdown"}] * 9)

    state = drive(
        world, scripted(*[("click_item", "Agency")] * 20), goal=GOAL, monkeypatch=monkeypatch, tmp_path=tmp_path, writer=writer
    )

    assert state.outcome == "stuck"
    p = handed_on(state, tmp_path)
    assert len(p["actions"]) == 7
    assert all(a["app"] == "Google Chrome" and a["url"] == FORMS for a in p["actions"])
    assert all(a["then"] == {"app": "Google Chrome", "url": FORMS, "changed_screen": False} for a in p["actions"])
    assert [(h["outcome"], h["focus"]) for h in p["handoffs"]] == [("stalled", "Open the '-Any-' dropdown")] * (MAX_STALLS - 1)
    # The last reading offered one more focus, which the run did not take: the next thing to try.
    assert p["last_focus"] == "Open the '-Any-' dropdown"
    assert p["current_screen"]["url"] == FORMS
    assert p["current_screen"]["text"] == ["Agency", "-Any-", "Apply Filters"]
    assert p["current_screen"]["raw"] == HANDOFF_RAW
    assert p["earlier_screens"] == []  # it never left the page it ended on


def test_an_unfollowed_focus_hands_on_with_the_focus_that_led_nowhere(monkeypatch, tmp_path):
    world = tickets()
    writer = FakeWriter(
        reviews=[
            {"focus": "Open the 'About' page", "answer": "I'll open the about page."},
            {"focus": "Open the 'About' page", "answer": "I could not open it."},
        ]
    )
    unsure = scripted(("click_item", "Tickets", 0.3), ("click_item", "Tickets", 0.3))

    state = drive(world, unsure, goal=GOAL, monkeypatch=monkeypatch, tmp_path=tmp_path, writer=writer)

    assert state.outcome == "unfollowed"
    p = handed_on(state, tmp_path)
    assert p["actions"] == []
    assert [(h["outcome"], h["focus"], h["said"]) for h in p["handoffs"]] == [
        ("low confidence", "Open the 'About' page", "I'll open the about page.")
    ]
    assert p["answer"] == "I could not open it."
    assert p["current_screen"]["url"] == HOME and p["current_screen"]["text"] == ["Home", "Tickets", "About"]


def test_low_confidence_with_the_handoffs_spent_hands_on_the_screens_passed(monkeypatch, tmp_path):
    world = tickets()
    writer = FakeWriter(reviews=[NOT_YET])

    state = drive(
        world,
        scripted(("click_item", "Tickets"), ("click_item", "Buy", 0.3)),
        goal=GOAL,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        writer=writer,
        handoffs=0,
    )

    assert state.outcome == "low confidence"
    p = handed_on(state, tmp_path)
    assert p["actions"] == [
        {
            "action": "clicked 'Tickets'",
            "app": "Google Chrome",
            "url": HOME,
            "then": {"app": "Google Chrome", "url": TICKETS, "changed_screen": True},
        }
    ]
    assert p["handoffs"] == [] and p["last_focus"] is None
    assert p["earlier_screens"] == [{"app": "Google Chrome", "url": HOME, "text": ["Home", "Tickets", "About"]}]
    assert p["current_screen"]["url"] == TICKETS and p["current_screen"]["text"] == ["Next show", "Buy", "Terms"]
    assert p["current_screen"]["raw"] == HANDOFF_RAW


def test_the_step_limit_hands_on_the_screen_each_action_led_to(monkeypatch, tmp_path):
    feed = "https://example.com/feed"
    world = World(
        [
            Page(name=f"list{n}", items=[f"Post {2 * n - 1}", f"Post {2 * n}"], url=feed, on={"scroll_down": f"list{n + 1}"})
            for n in range(1, 7)
        ]
    )

    state = drive(
        world,
        lambda state, questions: ("scroll_down", None),
        goal=GOAL,
        steps=3,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        writer=FakeWriter(reviews=[NOT_YET]),
    )

    assert state.outcome == "step limit"
    p = handed_on(state, tmp_path)
    assert [a["action"] for a in p["actions"]] == state.history and len(p["actions"]) == 3
    assert all(a["then"]["changed_screen"] for a in p["actions"])
    # Every list the run scrolled past, oldest first, and the one it ended on, read again for the answer.
    assert [s["text"] for s in p["earlier_screens"]] == [["Post 1", "Post 2"], ["Post 3", "Post 4"], ["Post 5", "Post 6"]]
    assert p["current_screen"]["text"] == ["Post 7", "Post 8"]


def test_nothing_helps_hands_on(monkeypatch, tmp_path):
    world = tickets()

    state = drive(
        world,
        scripted(("none", None)),
        goal=GOAL,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        writer=FakeWriter(reviews=[NOT_YET]),
    )

    assert state.outcome == "nothing helps"
    p = handed_on(state, tmp_path)
    assert p["actions"] == [] and p["earlier_screens"] == []
    assert p["current_screen"]["text"] == ["Home", "Tickets", "About"]


def test_a_packet_that_cannot_be_written_leaves_the_run_its_outcome(monkeypatch, tmp_path):
    """The packet is an extra: a fault building it is logged, and the run still ends as it stopped."""

    def broken(*_):
        raise ValueError("cannot build the packet")

    monkeypatch.setattr(runner, "handoff_packet", broken)
    state = drive(
        tickets(),
        scripted(("none", None)),
        goal=GOAL,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        writer=FakeWriter(reviews=[NOT_YET]),
    )

    assert state.outcome == "nothing helps"
    assert not (tmp_path / "run" / HANDOFF_FILE).exists()
    run = json.loads((tmp_path / "run" / "run.json").read_text())
    assert run["outcome"] == "nothing helps" and run["handoff"] is None
    assert "handoff not written" in (tmp_path / "run" / "run.log").read_text()


def test_an_achieved_run_hands_nothing_on(monkeypatch, tmp_path):
    state = drive(
        tickets(), scripted(("click_item", "Tickets"), ("done", None)), goal=GOAL, monkeypatch=monkeypatch, tmp_path=tmp_path
    )

    assert state.outcome == "done" and state.answer.achieved
    assert not (tmp_path / "run" / HANDOFF_FILE).exists()
    assert not (tmp_path / "run" / HANDOFF_RAW).exists()
    assert json.loads((tmp_path / "run" / "run.json").read_text())["handoff"] is None


def test_a_dry_run_hands_nothing_on(monkeypatch, tmp_path):
    state = drive(
        tickets(), scripted(("click_item", "Tickets")), goal=GOAL, monkeypatch=monkeypatch, tmp_path=tmp_path, act=False
    )

    assert state.outcome == "dry run"
    assert not (tmp_path / "run" / HANDOFF_FILE).exists()


def test_the_handoff_event_carries_the_packet_before_the_run_ends(monkeypatch, tmp_path):
    out = io.StringIO()

    drive(
        tickets(),
        scripted(("none", None)),
        goal=GOAL,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        writer=FakeWriter(reviews=[NOT_YET]),
        events=Events(out, io.StringIO()),
    )

    events = [json.loads(line) for line in out.getvalue().splitlines()]
    kinds = [e["event"] for e in events if e["event"] != "log"]
    assert kinds[-2:] == ["handoff", "end"]
    handoff = next(e for e in events if e["event"] == "handoff")
    assert handoff["file"] == str(tmp_path / "run" / HANDOFF_FILE)
    assert {k: v for k, v in handoff.items() if k not in ("event", "file")} == packet(tmp_path)


def test_the_packet_names_the_moves_but_never_the_users_email(monkeypatch, tmp_path):
    email = "someone@example.com"

    drive(
        tickets(),
        scripted(("none", None)),
        goal=GOAL,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        writer=FakeWriter(reviews=[NOT_YET]),
        email=email,
    )

    p = packet(tmp_path)
    assert "type_email" in p["moves"]
    assert email not in (tmp_path / "run" / HANDOFF_FILE).read_text()

"""`clicker --events`: what a front end such as the menu bar app reads off a run, and how it answers."""

from __future__ import annotations

import io
import json
from types import SimpleNamespace

from world import FakeWriter, Page, World, drive, scripted

from typesafe_computer_use import cli
from typesafe_computer_use.events import Events

GOAL = "find the 15 inch macbook"


def read(out: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in out.getvalue().splitlines()]


def milestones(out: io.StringIO) -> list[tuple]:
    """The events other than printed lines, as (event, the one field that tells them apart)."""
    keys = {"run": "act", "step": "step", "action": "text", "would": "text", "focus": "focus", "question": "text"}
    keys |= {"answer": "achieved", "end": "outcome"}
    return [(e["event"], e[keys[e["event"]]]) for e in read(out) if e["event"] != "log"]


def sizes() -> World:
    return World(
        [
            Page(
                name="sizes",
                items=["13 inch", "15 inch"],
                url="https://shop.example.com/sizes",
                on={"click:13 inch": "small", "click:15 inch": "large"},
            ),
            Page(name="small", items=["MacBook Air 13", "$140.00"], url="https://shop.example.com/13"),
            Page(name="large", items=["MacBook Air 15", "$210.00"], url="https://shop.example.com/15"),
        ]
    )


def test_every_line_is_one_json_object_and_flushed():
    out = io.StringIO()
    events = Events(out, io.StringIO())

    events("step", step=1)
    events.line("step 1: app='Chrome'")

    assert read(out) == [{"event": "step", "step": 1}, {"event": "log", "text": "step 1: app='Chrome'"}]


def test_a_question_waits_for_one_line_and_a_closed_stdin_declines():
    out = io.StringIO()

    assert Events(out, io.StringIO("15\r\nmore\n")).ask("13 or 15 inch?") == "15"
    assert Events(out, io.StringIO("")).ask("13 or 15 inch?") == ""
    assert milestones(out) == [("question", "13 or 15 inch?")] * 2


def test_a_run_reports_its_steps_question_and_answer_and_prints_nothing(monkeypatch, tmp_path, capsys):
    world = sizes()

    def policy(state: dict, questions: dict) -> tuple:
        if state["browser_active_tab_url"].endswith("/sizes"):
            said = state.get("user_said")
            return ("click_item", f"{said[0]['replied']} inch") if said else ("none", None)
        return ("done", None)

    def focus_on_the_reply(packet: dict) -> dict:
        return {"focus": f"Click '{packet['user_said'][0]['replied']} inch'"}

    writer = FakeWriter(reviews=[{"question": "13 or 15 inch?"}, focus_on_the_reply])
    out = io.StringIO()

    state = drive(
        world,
        policy,
        goal=GOAL,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        writer=writer,
        events=Events(out, io.StringIO("15\n")),
    )

    assert state.outcome == "done" and world.page.name == "large"
    assert milestones(out) == [
        ("run", True),
        ("step", 1),
        ("question", "13 or 15 inch?"),
        ("focus", "Click '15 inch'"),
        ("step", 2),
        ("action", "clicked '15 inch'"),
        ("step", 3),
        ("answer", True),
        ("end", "done"),
    ]
    end = read(out)[-1]
    assert end["folder"] == str(tmp_path / "run")
    assert end["why"] == "the classifier judged the goal already achieved on this screen"
    assert end["answer"] == state.answer.text and end["goal_achieved"] is True
    assert end["questions"] == [{"question": "13 or 15 inch?", "reply": "15"}]
    assert any(e["event"] == "log" and e["text"].startswith("run folder: ") for e in read(out))
    assert capsys.readouterr().out == ""  # stdout is the front end's: nothing but events reaches it


def test_a_declined_question_ends_the_run_with_the_answer_standing(monkeypatch, tmp_path):
    world = sizes()
    writer = FakeWriter(reviews=[{"question": "13 or 15 inch?"}])
    out = io.StringIO()

    state = drive(
        world,
        scripted(("none", None)),
        goal=GOAL,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        writer=writer,
        events=Events(out, io.StringIO()),
    )

    assert state.outcome == "nothing helps" and state.handoffs == []
    assert [m for m in milestones(out) if m[0] != "step"] == [
        ("run", True),
        ("question", "13 or 15 inch?"),
        ("end", "nothing helps"),
    ]


def test_a_dry_run_says_what_it_would_have_clicked(monkeypatch, tmp_path):
    world = sizes()
    out = io.StringIO()

    state = drive(
        world,
        scripted(("click_item", "15 inch")),
        goal=GOAL,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        events=Events(out),
        act=False,
    )

    assert state.outcome == "dry run" and world.log == []
    assert milestones(out) == [("run", False), ("step", 1), ("would", "click '15 inch'"), ("end", "dry run")]
    assert read(out)[-1]["why"] is None


def test_clicker_events_hands_the_run_its_events_and_their_questions(monkeypatch, tmp_path, capsys):
    seen = {}

    def run(cfg, ctx_factory, events=None):
        seen["events"] = events
        seen["ctx"] = ctx_factory(None, [])
        return SimpleNamespace(outcome="dry run")

    monkeypatch.setattr(cli, "_prepare", lambda: SimpleNamespace(describe=lambda: "openrouter ~typesafe/jev-latest"))
    monkeypatch.setattr(cli, "make_writer", lambda: None)
    monkeypatch.setattr(cli, "run", run)
    monkeypatch.setattr(cli.desktop, "default_browser", lambda: None)

    cli.main([GOAL, "--events", "--out", str(tmp_path / "run")])

    assert isinstance(seen["events"], Events)
    assert seen["ctx"].ask == seen["events"].ask  # a front end can always answer, with or without a terminal
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert lines[0] == {"event": "log", "text": "classifier: openrouter ~typesafe/jev-latest"}
    assert lines[1]["event"] == "log" and lines[1]["text"].startswith("writer disabled")

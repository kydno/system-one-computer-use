"""`clicker-takeover`: an LLM computer-use agent that goes on from a run's `handoff.json`.

Each scenario drives the real loop (see world.py) until it stops short of the goal and writes the
packet, then hands that run folder to `take_over` against the same world, with a fake OpenRouter
client in place of the model. The fake plays the model's turns from the request it is sent, so a
test can assert both what the model was told and what its actions did to the world. The pages and
goals are made up.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from world import CAPTURE, FakeWriter, Page, World, drive, row_box, scripted

from typesafe_computer_use import cli, config
from typesafe_computer_use.models import Abort
from typesafe_computer_use.platform_adapter import desktop
from typesafe_computer_use.runner import HANDOFF_FILE, STOPPED
from typesafe_computer_use.takeover import (
    NUDGE,
    READ_ONLY,
    TAKEOVER_FILE,
    TOOLS,
    TakeoverError,
    instructions,
    take_over,
)
from typesafe_computer_use.writer import ANSWER_IMAGE_EDGE

GOAL = "buy a ticket to the next show"
HOME = "https://example.com/"
TICKETS = "https://example.com/tickets"
FOCUS = "Click 'Buy' beside the next show"
SENT = ANSWER_IMAGE_EDGE / CAPTURE[0]  # the screenshot the model sees is the capture shrunk by this


def tickets() -> World:
    return World(
        [
            Page(name="home", items=["Home", "Tickets", "About"], url=HOME, on={"click:Tickets": "tickets"}),
            Page(name="tickets", items=["Next show", "Buy", "Terms"], url=TICKETS, on={"click:Buy": "checkout"}),
            Page(name="checkout", items=["Your ticket", "Pay"], url="https://example.com/checkout"),
        ]
    )


def stopped_short(world: World, monkeypatch, tmp_path, goal: str = GOAL, read_only: bool = False):
    """A run that clicks Tickets, is unsure of Buy, and ends with the writer suggesting it: a packet to take over."""
    state = drive(
        world,
        scripted(("click_item", "Tickets"), ("click_item", "Buy", 0.1)),
        goal=goal,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        writer=FakeWriter(reviews=[{"achieved": False, "answer": "Not there yet.", "focus": FOCUS}]),
        handoffs=0,
        read_only=read_only,
    )
    folder = tmp_path / "run"
    assert state.outcome == "low confidence" and (folder / HANDOFF_FILE).is_file()
    return folder


def at(row: int) -> dict:
    """The middle of a row, in pixels of the screenshot the model was sent."""
    x1, y1, x2, y2 = row_box(row)
    return {"x": round((x1 + x2) / 2 * SENT), "y": round((y1 + y2) / 2 * SENT)}


def call(name: str, n: int, **args) -> SimpleNamespace:
    return SimpleNamespace(type="function_call", call_id=f"call_{n}", name=name, arguments=json.dumps(args))


def said(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="message", content=[SimpleNamespace(type="output_text", text=text)])


class FakeOpenRouter:
    """Stands in for `openai.OpenAI` on OpenRouter: `responses.create` plays one scripted turn per request.

    Each turn is a list of output items, or a callable(request) returning one. Every reply reports
    the same usage, with a cost, as OpenRouter's do.
    """

    def __init__(self, *turns):
        self.turns = list(turns)
        self.requests: list[dict] = []
        self.responses = SimpleNamespace(create=self._create)

    def _create(self, **request):
        self.requests.append(json.loads(json.dumps(request)))  # a copy: the takeover goes on appending to its input
        turn = self.turns.pop(0)
        output = turn(request) if callable(turn) else turn
        usage = SimpleNamespace(
            input_tokens=1000, input_tokens_details=SimpleNamespace(cached_tokens=400), output_tokens=50, cost=0.0002
        )
        return SimpleNamespace(output=output, usage=usage)


def taken_over(folder) -> dict:
    return json.loads((folder / TAKEOVER_FILE).read_text())


def images(request: dict) -> list[str]:
    """Every screenshot in a request, oldest first."""
    found = []
    for item in request["input"]:
        parts = item.get("content") if "content" in item else item.get("output")
        if isinstance(parts, list):
            found += [p["image_url"] for p in parts if p.get("type") == "input_image"]
    return found


def test_the_takeover_is_told_the_story_and_goes_on_from_where_the_run_stopped(monkeypatch, tmp_path):
    world = tickets()
    folder = stopped_short(world, monkeypatch, tmp_path)
    packet = json.loads((folder / HANDOFF_FILE).read_text())
    model = FakeOpenRouter(
        [said("The run reached the tickets page; Buy is next."), call("click", 1, button="left", clicks=1, **at(1))],
        [call("finish", 2, achieved=True, answer="The ticket is in the cart.")],
    )

    taken = take_over(folder, model, delay=0)

    # The story reached the model: the goal, why the run stopped, every action and where it led,
    # the writer's last answer and the step it suggested, and the screen the run ended on.
    system = model.requests[0]["instructions"]
    assert GOAL in system and STOPPED["low confidence"] in system
    story = json.loads(system[system.index("{") :])
    assert story["actions"] == packet["actions"] and story["actions"][0]["action"] == "clicked 'Tickets'"
    assert story["last_focus"] == FOCUS and story["answer"] == "Not there yet."
    assert story["current_screen"] == {
        "app": "Google Chrome",
        "url": TICKETS,
        "field": None,
        "text": ["Next show", "Buy", "Terms"],
    }
    assert story["earlier_screens"] == packet["earlier_screens"] and "click_item" in story["moves"]
    first = model.requests[0]["input"]
    assert len(first) == 1 and GOAL in first[0]["content"][0]["text"] and len(images(model.requests[0])) == 1
    assert model.requests[0]["tools"] == TOOLS and model.requests[0]["model"] == config.DEFAULT_TAKEOVER_MODEL
    assert model.requests[0]["reasoning"] == {"effort": config.DEFAULT_TAKEOVER_REASONING}

    # The click landed on Buy, by the screenshot's pixels, and the next turn saw the page it led to.
    assert world.log[-1] == "click:Buy" and world.page.name == "checkout"
    second = model.requests[1]["input"]
    assert second[1] == {"role": "assistant", "content": "The run reached the tickets page; Buy is next."}
    assert second[2]["type"] == "function_call" and second[2]["call_id"] == "call_1"
    assert second[3]["type"] == "function_call_output" and second[3]["output"][0]["text"] == "clicked at ({x}, {y})".format(
        **at(1)
    )
    assert len(images(model.requests[1])) == 2

    assert taken.outcome == "done" and taken.achieved is True
    report = taken_over(folder)
    assert report["outcome"] == "done" and report["goal_achieved"] is True and report["goal"] == GOAL
    assert report["answer"] == "The ticket is in the cart." and report["steps"] == 2
    assert [(a["step"], a["action"], a["result"]) for a in report["actions"]] == [
        (1, "click", "clicked at ({x}, {y})".format(**at(1))),
        (2, "finish", "finished"),
    ]
    assert report["usage"] == {
        config.DEFAULT_TAKEOVER_MODEL: {
            "requests": 2,
            "input_tokens": 1200,
            "cached_input_tokens": 800,
            "output_tokens": 100,
            "cost": pytest.approx(0.0004),
        }
    }
    assert report["cost"] == pytest.approx(0.0004)
    assert (folder / "takeover-step-000.png").is_file() and (folder / "takeover-step-001.png").is_file()
    assert "finished: achieved" in (folder / "takeover.log").read_text()


def test_every_action_goes_through_the_adapter(monkeypatch, tmp_path):
    world = World(
        [
            Page(name="home", items=["Search", "Results"], url=HOME, field="Search", on={"enter": "results"}),
            Page(name="results", items=["First", "Second"], url=HOME, on={"scroll_down": "results"}),
        ]
    )
    folder = stopped_short_on(world, monkeypatch, tmp_path)
    waited = []
    monkeypatch.setattr(desktop, "sleep_watching", lambda seconds: waited.append(seconds))
    model = FakeOpenRouter(
        [
            call("type_text", 1, text="tickets"),
            call("press_key", 2, key="return", command=False, shift=False, option=False, control=False),
        ],
        [call("scroll", 3, direction="down", **at(0)), call("wait", 4, seconds=60), call("screenshot", 5)],
        [call("finish", 6, achieved=False, answer="No show is listed.")],
    )

    taken = take_over(folder, model, delay=0.5)

    assert world.log[-3:] == ["type:tickets", "enter", "scroll_down"] and world.typed["Search"] == "tickets"
    assert world.wheel[-1] == pytest.approx((at(0)["x"] / SENT / 2, at(0)["y"] / SENT / 2), abs=1)
    # A wait asks for no more than the cap, and every turn that acted settles before the next look.
    assert waited == [0.5, 10.0, 0.5]
    assert taken.outcome == "handed back" and taken.achieved is False and taken.answer == "No show is listed."


def stopped_short_on(world: World, monkeypatch, tmp_path):
    """A run on `world` that the classifier gives up on at once."""
    drive(
        world,
        scripted(("none", None)),
        goal=GOAL,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        writer=FakeWriter(reviews=[{"achieved": False, "answer": "Not there yet."}]),
    )
    return tmp_path / "run"


def test_what_cannot_be_done_is_refused_and_the_takeover_goes_on(monkeypatch, tmp_path):
    world = World([Page(name="login", items=["Email", "Password", "Sign in"], url=HOME, field="Password")])
    folder = stopped_short_on(world, monkeypatch, tmp_path)
    before = list(world.log)
    model = FakeOpenRouter(
        [
            call("click", 1, button="left", clicks=1, x=5000, y=10),
            call("type_text", 2, text="hunter2"),
            call("press_key", 3, key="f13", command=False, shift=False, option=False, control=False),
            call("teleport", 4),
            SimpleNamespace(type="function_call", call_id="call_5", name="click", arguments="not json"),
        ],
        [call("finish", 6, achieved=False, answer="Sign in first.")],
    )

    taken = take_over(folder, model, delay=0)

    assert world.log == before and "Password" not in world.typed
    results = [a["result"] for a in taken.actions[:5]]
    assert results[0].startswith("refused: (5000, 10) is outside")
    assert results[1] == "refused: the focused field holds a credential, which only the user may type"
    assert results[2] == "refused: 'f13' is not a key this tool presses"
    assert results[3] == "refused: there is no tool named 'teleport'"
    assert results[4] == "refused: the arguments are not a JSON object"
    # Each refusal went back to the model as the output of its call.
    outputs = [i for i in model.requests[1]["input"] if i.get("type") == "function_call_output"]
    assert [o["call_id"] for o in outputs] == [f"call_{n}" for n in range(1, 6)]
    assert taken.outcome == "handed back"


def test_a_model_that_only_talks_is_reminded_once_then_the_takeover_ends(monkeypatch, tmp_path):
    folder = stopped_short(tickets(), monkeypatch, tmp_path)
    model = FakeOpenRouter([said("I would click Buy.")], [said("Buy is the next step.")])

    taken = take_over(folder, model, delay=0)

    assert model.requests[1]["input"][-1] == {"role": "user", "content": NUDGE}
    assert taken.outcome == "no finish" and taken.answer == "Buy is the next step."
    assert taken_over(folder)["goal_achieved"] is None


def test_the_step_limit_ends_the_takeover(monkeypatch, tmp_path):
    folder = stopped_short(tickets(), monkeypatch, tmp_path)
    model = FakeOpenRouter(*[[call("screenshot", n)] for n in range(3)])

    taken = take_over(folder, model, steps=3, delay=0)

    assert taken.outcome == "step limit" and taken.steps == 3 and len(model.requests) == 3


def test_the_abort_corner_stops_a_takeover_and_the_report_is_still_written(monkeypatch, tmp_path):
    world = tickets()
    folder = stopped_short(world, monkeypatch, tmp_path)

    def corner():
        raise Abort("mouse in top-left corner")

    monkeypatch.setattr(desktop, "check_abort", corner)
    model = FakeOpenRouter([call("click", 1, button="left", clicks=1, **at(1))])

    taken = take_over(folder, model, delay=0)

    assert world.page.name == "tickets"
    assert taken.outcome == "aborted (mouse in top-left corner)" and taken_over(folder)["outcome"] == taken.outcome


def test_a_read_only_goal_is_told_to_change_nothing(monkeypatch, tmp_path):
    folder = stopped_short(tickets(), monkeypatch, tmp_path, goal="when is the next show", read_only=True)
    packet = json.loads((folder / HANDOFF_FILE).read_text())

    assert packet["read_only"] is True and READ_ONLY in instructions(packet)
    assert READ_ONLY not in instructions({**packet, "read_only": False})
    assert "handoff-raw.png" not in instructions(packet)  # the file name means nothing to the model


def test_only_a_run_folder_with_a_packet_not_yet_taken_over_is_taken_over(monkeypatch, tmp_path):
    with pytest.raises(TakeoverError, match="does not exist"):
        take_over(tmp_path, FakeOpenRouter())
    folder = stopped_short(tickets(), monkeypatch, tmp_path)
    take_over(folder, FakeOpenRouter([call("finish", 1, achieved=False, answer="Not yet.")]), delay=0)
    with pytest.raises(TakeoverError, match="already taken over"):
        take_over(folder, FakeOpenRouter())


def test_the_command_needs_an_openrouter_key(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "DOTENV", tmp_path / ".env")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    with pytest.raises(SystemExit, match="needs OPENROUTER_API_KEY"):
        cli.takeover([str(tmp_path)])


def test_the_takeover_model_and_its_reasoning_come_from_the_environment(monkeypatch):
    monkeypatch.delenv("CLICKER_TAKEOVER_MODEL", raising=False)
    monkeypatch.delenv("CLICKER_TAKEOVER_REASONING", raising=False)
    assert (config.takeover_model(), config.takeover_reasoning()) == ("openai/gpt-6-luna", "medium")
    monkeypatch.setenv("CLICKER_TAKEOVER_MODEL", "some/other-model")
    assert config.takeover_reasoning() is None  # a named model keeps its own
    monkeypatch.setenv("CLICKER_TAKEOVER_REASONING", "high")
    assert (config.takeover_model(), config.takeover_reasoning()) == ("some/other-model", "high")

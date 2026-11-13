"""What a run may do: `full` takes every action, `ask` asks before one that would change something, `look` never
takes one. Driven through the real loop, as the scenarios are, with the changes question answered by the action."""

from __future__ import annotations

import io
import json
from dataclasses import replace

import pytest
from world import FakeWriter, Page, World, drive, scripted

from typesafe_computer_use import config
from typesafe_computer_use.events import Events
from typesafe_computer_use.models import Field
from typesafe_computer_use.runner import STOPPED, field_name, said_yes

GOAL = "check whether the shoes are in stock"


def shop() -> World:
    return World(
        [
            Page(
                name="product",
                items=["Size 10", "Reviews", "Add to Bag"],
                url="https://shop.example.com/shoe",
                on={"click:Add to Bag": "bag", "click:Reviews": "reviews"},
            ),
            Page(name="bag", items=["Bag", "1 item"], url="https://shop.example.com/bag"),
            Page(name="reviews", items=["Reviews", "In stock in every size"], url="https://shop.example.com/reviews"),
        ]
    )


def bag_changes(state: dict) -> float:
    """Adding to the bag changes something; nothing else on the shop does."""
    return 0.9 if "Add to Bag" in state["action"] else 0.05


def test_full_takes_every_action_without_asking(monkeypatch, tmp_path):
    world = shop()

    state = drive(
        world, scripted(("click_item", "Add to Bag"), ("done", None)), goal=GOAL, monkeypatch=monkeypatch, tmp_path=tmp_path
    )

    assert world.log == ["click:Add to Bag"]
    assert world.fake.change_states == []  # full never asks the question
    assert state.held == []


def test_look_holds_an_action_that_changes_something(monkeypatch, tmp_path):
    world = shop()
    writer = FakeWriter(reviews=[{"achieved": False}])

    state = drive(
        world,
        scripted(("click_item", "Add to Bag")),
        goal=GOAL,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        permissions="look",
        changes=bag_changes,
        writer=writer,
    )

    assert world.log == []
    assert world.mouse == []
    assert state.outcome == "look only"
    assert state.held == [
        {"step_action": 1, "action": "click 'Add to Bag'", "changes": 0.9, "permissions": "look", "result": "held"}
    ]
    assert writer.packets[0]["why_the_run_stopped"] == STOPPED["look only"]
    assert "only look" in writer.packets[0]["what_the_run_may_do"]
    asked = world.fake.change_states[0]
    assert asked["action"] == "click 'Add to Bag'" and asked["goal"] == GOAL
    summary = json.loads((tmp_path / "run" / "run.json").read_text())
    assert summary["permissions"] == "look" and summary["held"][0]["result"] == "held"


def test_look_takes_an_action_that_only_reads(monkeypatch, tmp_path):
    world = shop()

    state = drive(
        world,
        scripted(("click_item", "Reviews"), ("done", None)),
        goal=GOAL,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        permissions="look",
        changes=bag_changes,
    )

    assert world.log == ["click:Reviews"]
    assert state.outcome == "done"
    assert state.held == []


def test_look_leaves_scrolling_and_going_to_a_site_unasked(monkeypatch, tmp_path):
    world = shop()

    drive(
        world,
        scripted(("scroll_down", None), ("done", None)),
        goal=GOAL,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        permissions="look",
        changes=lambda state: 1.0,
    )

    assert world.fake.change_states == []


def test_ask_takes_the_action_once_the_user_says_yes(monkeypatch, tmp_path):
    world = shop()

    state = drive(
        world,
        scripted(("click_item", "Add to Bag"), ("done", None)),
        goal="add the shoes to my bag",
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        permissions="ask",
        changes=bag_changes,
        replies=["Yes please!"],
    )

    assert world.asked == ["May I click 'Add to Bag'? It would change something. Reply yes to go ahead."]
    assert world.log == ["activate", "click:Add to Bag"]  # the app goes back to the front after the question
    assert state.outcome == "done"
    assert state.held[0]["result"] == "allowed" and state.held[0]["reply"] == "Yes please!"


def test_ask_stops_when_the_user_says_no_and_the_writer_hears_why(monkeypatch, tmp_path):
    world = shop()
    writer = FakeWriter(reviews=[{"achieved": False}])

    state = drive(
        world,
        scripted(("click_item", "Add to Bag")),
        goal=GOAL,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        permissions="ask",
        changes=bag_changes,
        replies=["no, just read the page"],
        writer=writer,
    )

    assert world.log == ["activate"]  # back to the front after the question, and nothing clicked
    assert state.outcome == "declined"
    assert state.held[0]["result"] == "declined"
    assert writer.packets[0]["user_said"][0]["replied"] == "no, just read the page"


def test_ask_with_nobody_to_ask_only_looks(monkeypatch, tmp_path):
    world = shop()

    state = drive(
        world,
        scripted(("click_item", "Add to Bag")),
        goal=GOAL,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        permissions="ask",
        changes=bag_changes,
        writer=FakeWriter(reviews=[{"achieved": False}]),
    )

    assert world.log == []
    assert state.outcome == "look only"


def test_permissions_setting_reads_the_environment(monkeypatch):
    monkeypatch.delenv("CLICKER_PERMISSIONS", raising=False)
    assert config.permissions() == "full"
    monkeypatch.setenv("CLICKER_PERMISSIONS", " Ask ")
    assert config.permissions() == "ask"
    monkeypatch.setenv("CLICKER_PERMISSIONS", "sometimes")
    with pytest.raises(ValueError):
        config.permissions()


@pytest.mark.parametrize("reply", ["yes", "Yes please", "ok, go ahead", "go ahead", "y", "Sure."])
def test_a_yes_as_people_type_it(reply):
    assert said_yes(reply)


@pytest.mark.parametrize("reply", ["", "no", "nope, just read it", "not yet", "yesterday"])
def test_anything_else_is_a_no(reply):
    assert not said_yes(reply)


def chat() -> World:
    return World(
        [
            Page(
                name="chat",
                items=["Ben", "Message"],
                url="https://www.example.com/chat/ben?tab=1",
                field="Message",
            )
        ]
    )


def typing_changes(state: dict) -> float:
    return 0.9 if state["action"].startswith("type") else 0.05


def fills(writer: FakeWriter) -> int:
    """How many times the writer was asked what to type."""
    return sum(
        set(r["output_config"]["format"]["schema"]["properties"]) == {"fill", "text", "submit", "reason"} for r in writer.requests
    )


def test_ask_shows_the_words_before_typing_them_and_tells_the_app(monkeypatch, tmp_path):
    world = chat()
    writer = FakeWriter(text="see you at 6")
    out = io.StringIO()

    state = drive(
        world,
        scripted(("type_text", None), ("done", None)),
        goal="tell Ben I'll see him at 6",
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        permissions="ask",
        changes=typing_changes,
        writer=writer,
        events=Events(out, io.StringIO("yes\n")),
    )

    events = [json.loads(line) for line in out.getvalue().splitlines()]
    (card,) = [e for e in events if e["event"] == "permission"]
    question = "May I type 'see you at 6' into Message? It would change something. Reply yes to go ahead."
    assert card == {
        "event": "permission",
        "kind": "type",
        "title": "Type into Message",
        "text": "see you at 6",
        "where": "Google Chrome · example.com/chat/ben",
        "question": question,
    }
    # The card comes first, then the question the app answers.
    assert [e["event"] for e in events].index("permission") + 1 == [e["event"] for e in events].index("question")
    assert world.typed["Message"] == "see you at 6"
    assert fills(writer) == 1  # written once, before asking, and those words typed
    assert state.held[0]["action"] == "type 'see you at 6' into Message"


def test_a_field_with_no_label_is_named_by_its_role_in_words():
    blank = Field(role="AXTextArea", label="", placeholder="", value="", x=0, y=0, w=10, h=10)
    assert field_name(blank) == "the text area"
    assert field_name(replace(blank, placeholder="Search")) == "Search"

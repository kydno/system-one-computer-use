"""Run folders for the eval kit's tests, made by the real loop on the simulated computer.

The kit reads what a real run leaves behind, so its tests make that the same way: `drive` runs the real
`runner.run` against a `World`, and the folder it writes is what `harvest` reads. No test holds a real
screen's text.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from world import FakeTypeSafe, FakeWriter, Page, World, drive, scripted

from typesafe_computer_use.evals.cases import Case
from typesafe_computer_use.evals.store import Home

BOOKMARKS = "chrome://bookmarks/"


def popup_world() -> World:
    """A bubble over the page: Organise sits under it, and an off-screen control is also offered."""
    return World(
        [
            Page(
                name="bubble",
                items=["Bookmarks", ("Organise", "button"), "Restore pages?", ("Close", "button"), ("Restore", "button")],
                url=BOOKMARKS,
                popup="Restore pages?",
                under_popup=("Organise",),
                offscreen=("Show all",),
                on={"click:Close": "manager"},
            ),
            Page(name="manager", items=["Bookmarks", ("Organise", "button")], url=BOOKMARKS, on={"click:Organise": "menu"}),
            Page(name="menu", items=["Bookmarks", "Add new folder"], url=BOOKMARKS),
        ]
    )


def form_world() -> World:
    """A search box with a dated listing under it: a focused field, and a date for the clock to count from."""
    return World(
        [
            Page(
                name="search",
                items=["Search", "Coldplay Oct 13 2030", "Buy"],
                url="https://example.com/",
                field="Search",
                on={"enter": lambda w: "results" if w.typed.get("Search") == "coldplay" else None},
            ),
            Page(name="results", items=["First result", "Second result"], url="https://example.com/results"),
        ]
    )


def run_popup(monkeypatch, tmp_path: Path):
    world = popup_world()
    state = drive(
        world,
        scripted(("click_item", "Organise"), ("done", None)),
        goal="make a new folder on the bookmarks bar",
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
    )
    return world, state


def run_form(monkeypatch, tmp_path: Path, act: bool = True):
    world = form_world()
    state = drive(
        world,
        scripted(("type_text", None), ("press_enter", None), ("done", None)),
        goal="search for coldplay",
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        writer=FakeWriter(text="coldplay"),
        act=act,
    )
    return world, state


def home_with(root: Path, *drives: tuple[Path, str]) -> Home:
    """A checkout's worth of `runs/`: each (folder a drive wrote, name to file it under)."""
    for source, name in drives:
        shutil.copytree(source / "run", root / "runs" / name)
    return Home(root)


def echo_factory(cases: list[Case]):
    """A client factory whose classifier picks exactly what each case's run picked."""

    def factory(repeat: int) -> FakeTypeSafe:
        remaining = iter(cases)

        def policy(state: dict, questions: dict):
            picked = next(remaining).picked
            return picked["kind"], picked["item_text"] if picked["kind"] == "click_item" else None

        return FakeTypeSafe(policy)

    return factory

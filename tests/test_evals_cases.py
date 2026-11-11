"""The eval kit's cases: a saved step frozen, and rebuilt into the request the live loop sent."""

from __future__ import annotations

import json

from evals_support import home_with, run_form, run_moves, run_popup

from typesafe_computer_use.evals import cases
from typesafe_computer_use.evals.store import Home, checkout_root


def sent(world, index: int) -> dict:
    """What the loop's classifier received on a step, through JSON as a run folder holds it."""
    return json.loads(json.dumps(world.fake.states[index]))


def test_a_frozen_step_rebuilds_into_exactly_the_request_that_was_sent(monkeypatch, tmp_path):
    world, _ = run_popup(monkeypatch, tmp_path / "a")
    folder = tmp_path / "a" / "run"

    found = cases.harvest_run(folder)

    assert len(found) == len(world.fake.states) == 2
    for i, case in enumerate(found):
        assert case.state == sent(world, i)
        assert case.criteria["item"] == world.fake.asked[i]["item"].criteria
        assert cases.fidelity(case) == []
    first = found[0]
    assert first.id == "run/001" and first.acted and first.achieved is True
    assert first.picked["kind"] == "click_item" and first.picked["item_text"] == "Organise"
    assert [c.step for c in found] == [1, 2]


def test_a_popup_an_offscreen_control_and_a_form_field_survive_the_round_trip(monkeypatch, tmp_path):
    popup_world, _ = run_popup(monkeypatch, tmp_path / "a")
    (bubble, _) = cases.harvest_run(tmp_path / "a" / "run")
    rebuilt = cases.rebuild(bubble)

    (organise,) = [i for i in rebuilt.items if i.text == "Organise"]
    assert rebuilt.screen.covered[organise.index].title == "'Restore pages?'"
    assert [node.label for node in rebuilt.screen.offscreen] == ["Show all"]
    assert "offscreen" in bubble.criteria

    form_world, _ = run_form(monkeypatch, tmp_path / "b")
    (typing, *_) = cases.harvest_run(tmp_path / "b" / "run")
    assert typing.field["label"] == "Search"
    assert cases.rebuild(typing).screen.field.label == "Search"
    assert cases.fidelity(typing) == []
    assert popup_world is not form_world


def test_the_request_counts_dates_from_the_steps_own_clock_not_the_machines(monkeypatch, tmp_path):
    run_form(monkeypatch, tmp_path / "a")
    (case, *_) = cases.harvest_run(tmp_path / "a" / "run")
    case.state["now"] = {"local_time": "2030-10-01 09:00 Tuesday", "timezone": "UTC", "today": "2030-10-01"}

    state, questions = cases.request(case)

    (dated,) = [i for i in state["screen_items_in_reading_order"] if "Oct 13" in i["text"]]
    assert dated["when"] == "dated 2030-10-13 (in 12 days)"
    assert state["now"]["today"] == "2030-10-01"
    assert "in 12 days" in questions["item"].criteria[str(dated["i"])]


def test_a_case_the_current_code_builds_differently_says_which_part(monkeypatch, tmp_path):
    run_popup(monkeypatch, tmp_path / "a")
    (case, *_) = cases.harvest_run(tmp_path / "a" / "run")
    case.criteria["kind"]["scroll_down"] = "Scroll down. (the wording of an older version)"

    assert cases.fidelity(case) == ["kind"]


def test_harvest_freezes_each_run_once_and_a_forced_harvest_freezes_it_again(monkeypatch, tmp_path):
    run_popup(monkeypatch, tmp_path / "a")
    run_form(monkeypatch, tmp_path / "b")
    home = home_with(tmp_path / "home", (tmp_path / "a", "20261101-000000"), (tmp_path / "b", "20261101-000100"))

    first = cases.harvest(home)
    again = cases.harvest(home)
    forced = cases.harvest(home, force=True)

    assert first == {"runs": 2, "cases": 5, "new_cases": 5}
    assert again == {"runs": 2, "cases": 5, "new_cases": 0}
    assert forced["new_cases"] == 5
    assert {c.run for c in cases.load_cases(home)} == {"20261101-000000", "20261101-000100"}
    assert [c.id for c in cases.load_cases(home, ["20261101-000100"])] == [f"20261101-000100/00{n}" for n in (1, 2, 3)]


def test_a_damaged_step_is_left_out_not_guessed_at(monkeypatch, tmp_path):
    run_popup(monkeypatch, tmp_path / "a")
    folder = tmp_path / "a" / "run"
    (folder / "step-002-payload.txt").write_text("nothing useful", encoding="utf-8")

    assert [c.step for c in cases.harvest_run(folder)] == [1]


def test_a_run_judged_achieved_gives_silver_labels_and_a_gold_label_replaces_one(monkeypatch, tmp_path):
    run_popup(monkeypatch, tmp_path / "a")
    run_form(monkeypatch, tmp_path / "b", act=False)  # a dry run: nothing it picked was carried out
    home = home_with(tmp_path / "home", (tmp_path / "a", "20261101-000000"), (tmp_path / "b", "20261101-000100"))
    cases.harvest(home)
    every = cases.load_cases(home)
    popup_cases = [c for c in every if c.run == "20261101-000000"]

    assert all(cases.expected(c, {}) is None for c in every if c.run == "20261101-000100")
    assert cases.expected(popup_cases[0], {}) == (
        {"kind": "click_item", "item": str(popup_cases[0].picked["item"]), "item_text": "Organise"},
        "silver",
    )
    assert cases.expected(popup_cases[1], {})[0] == {"kind": "done"}

    gold = {popup_cases[0].id: {"kind": "press_escape"}}
    assert cases.expected(popup_cases[0], gold) == ({"kind": "press_escape"}, "gold")
    assert [c.id for c, _, _ in cases.select(every, gold, "gold")] == [popup_cases[0].id]
    assert len(cases.select(every, gold, "silver")) == 1
    assert len(cases.select(every, gold, "labeled")) == 2
    assert len(cases.select(every, gold, "all")) == len(every)


def test_sizes_count_what_is_sent_and_leave_out_a_question_answered_in_code(monkeypatch, tmp_path):
    run_popup(monkeypatch, tmp_path / "a")
    (bubble, _) = cases.harvest_run(tmp_path / "a" / "run")

    state, questions = cases.request(bubble)
    parts = cases.sizes(state, questions)

    assert "offscreen" in questions and "q_offscreen" not in parts  # one label: nothing to ask
    assert parts["items_in_state"] < parts["state"] < parts["total"]
    assert parts["total"] > parts["state"] + parts["q_item"] + parts["q_kind"]


def test_the_main_checkout_is_found_from_inside_a_worktree(tmp_path):
    main = tmp_path / "main"
    (main / ".git" / "worktrees" / "feature").mkdir(parents=True)
    tree = main / ".claude" / "worktrees" / "feature"
    (tree / "sub").mkdir(parents=True)
    (tree / ".git").write_text(f"gitdir: {main / '.git' / 'worktrees' / 'feature'}\n", encoding="utf-8")

    assert checkout_root(tree / "sub") == main.resolve()
    assert checkout_root(main) == main.resolve()
    assert Home(main).runs == main / "runs" and Home(main).private == main / ".private" / "evals"


def test_a_step_whose_run_was_offered_the_moves_rebuilds_with_them_and_a_plain_step_without(monkeypatch, tmp_path):
    world, _ = run_moves(monkeypatch, tmp_path / "m")
    (selecting, stopping) = cases.harvest_run(tmp_path / "m" / "run")

    assert "press_shortcut" in selecting.criteria["kind"] and selecting.picked["kind"] == "press_shortcut"
    assert cases.rebuild(selecting).moves is True
    assert cases.fidelity(selecting) == [] and cases.fidelity(stopping) == []  # rebuilt as it was sent, with no flag given
    state, questions = cases.request(selecting)
    assert "press_shortcut" in questions["kind"].criteria and state == json.loads(json.dumps(world.fake.states[0]))

    # Forcing the moves off asks the question the saved run was never asked, so it no longer matches.
    assert "press_shortcut" not in cases.request(selecting, moves=False)[1]["kind"].criteria

    run_popup(monkeypatch, tmp_path / "p")
    (plain, _) = cases.harvest_run(tmp_path / "p" / "run")
    assert cases.rebuild(plain).moves is False
    assert "press_shortcut" not in cases.request(plain)[1]["kind"].criteria
    assert "press_shortcut" in cases.request(plain, moves=True)[1]["kind"].criteria  # --moves forces it on for any case

"""`clicker-eval` end to end on run folders the real loop wrote, and the digest on folders written by hand."""

from __future__ import annotations

import json

import httpx
import pytest
from evals_support import home_with, run_form, run_popup

from typesafe_computer_use.evals import cli, decisions, digest, report, size
from typesafe_computer_use.evals.store import Home

POPUP, FORM = "20261101-000000", "20261101-000100"


@pytest.fixture
def checkout(monkeypatch, tmp_path):
    """A checkout holding two finished runs; git is not asked, and the key is a placeholder."""
    run_popup(monkeypatch, tmp_path / "a")
    run_form(monkeypatch, tmp_path / "b")
    monkeypatch.setattr(report, "git_state", lambda root: {"git_commit": "abc12345", "git_dirty": False})
    monkeypatch.setattr(size, "git_state", lambda root: {"git_commit": "abc12345", "git_dirty": False})
    monkeypatch.setenv("OPENROUTER_API_KEY", "placeholder")
    return home_with(tmp_path / "home", (tmp_path / "a", POPUP), (tmp_path / "b", FORM))


def eval_run(home: Home, capsys, *argv: str) -> tuple[int, str, str]:
    code = cli.main(["--home", str(home.root), *argv])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_freeze_check_show_and_label_a_case(checkout, capsys):
    assert eval_run(checkout, capsys, "harvest")[1].startswith("2 runs frozen, 5 cases (5 new)")
    assert "5 of 5 cases rebuild exactly as they were sent" in eval_run(checkout, capsys, "check")[1]

    code, shown, _ = eval_run(checkout, capsys, "show", f"{POPUP}/001")
    assert code == 0 and "goal: make a new folder on the bookmarks bar" in shown
    assert ">>" in shown and "'Organise'" in shown and "Restore pages?" not in shown.split("answer model")[0].split("picked:")[0]

    only = eval_run(checkout, capsys, "show", f"{POPUP}/001", "--grep", "organise")[1]
    assert "showing 1" in only

    code, said, _ = eval_run(
        checkout, capsys, "label", f"{POPUP}/001", "--kind", "click_item", "--text", "Close", "--note", "dismiss first"
    )
    assert code == 0 and said.startswith(f"labelled {POPUP}/001")
    assert eval_run(checkout, capsys, "labels")[1].splitlines()[-1] == "1 gold labels"
    assert json.loads(checkout.labels.read_text(encoding="utf-8").splitlines()[0])["note"] == "dismiss first"


def test_a_label_the_step_did_not_offer_or_cannot_name_is_refused(checkout, capsys):
    eval_run(checkout, capsys, "harvest")

    code, _, err = eval_run(checkout, capsys, "label", f"{POPUP}/001", "--kind", "teleport")
    assert code == 2 and "was not offered at this step" in err

    code, _, err = eval_run(checkout, capsys, "label", f"{POPUP}/001", "--kind", "click_item")
    assert code == 2 and "needs --item INDEX or --text TEXT" in err

    code, _, err = eval_run(checkout, capsys, "label", f"{POPUP}/001", "--kind", "click_item", "--text", "No such item")
    assert code == 2 and "0 items read" in err

    code, _, err = eval_run(checkout, capsys, "label", f"{POPUP}/001", "--kind", "use_browser", "--site", "nowhere")
    assert code == 2 and "use_browser needs --site" in err

    code, _, err = eval_run(checkout, capsys, "show", "no-such-run/001")
    assert code == 2 and "no case" in err
    assert not checkout.labels.exists()


def test_size_keeps_a_baseline_and_a_later_measurement_is_set_against_it(checkout, capsys):
    assert eval_run(checkout, capsys, "size")[0] == 2  # nothing frozen yet: the command says what to run
    eval_run(checkout, capsys, "harvest")

    first = eval_run(checkout, capsys, "size", "--save-baseline")[1]
    assert "over 5 cases" in first and "saved as the baseline" in first

    again = eval_run(checkout, capsys, "size")[1]
    assert "against the baseline" in again and "+0.0%" in again
    assert len(list(checkout.passes.glob("*-size.json"))) >= 1


def reply_first_option(request: httpx.Request) -> httpx.Response:
    asked = json.loads(request.content)["questions"]
    answers = {
        name: {"type": "choice", "choice": next(iter(q["criteria"])), "confidence": 0.9, "probabilities": {}}
        for name, q in asked.items()
    }
    return httpx.Response(
        200, json={"model": "vendor/model-1", "usage": {"input_tokens": 9, "output_tokens": 1, "cost": 0.001}, "answers": answers}
    )


def test_a_pass_that_asks_a_model_needs_an_open_batch_and_is_recorded_as_numbers_only(checkout, capsys, monkeypatch):
    real = decisions.EvalClient
    monkeypatch.setattr(decisions, "EvalClient", lambda *a, **k: real(*a, **k, transport=httpx.MockTransport(reply_first_option)))
    eval_run(checkout, capsys, "harvest")

    code, _, err = eval_run(checkout, capsys, "decisions")
    assert code == 2 and "no batch" in err and not checkout.cache.exists()

    code, out, _ = eval_run(checkout, capsys, "decisions", "--plan")
    assert code == 0 and "5 requests, 0 already cached, 5 new" in out and "no open batch" in out

    assert eval_run(checkout, capsys, "batch", "open", "--cap", "1", "--iterations", "2", "--name", "t1")[1].startswith(
        "batch t1: $0.0000 of $1.00"
    )
    code, out, _ = eval_run(checkout, capsys, "decisions", "--repeats", "1")
    assert code == 0 and '"requests_sent": 5' in out and "batch t1: $0.0050 of $1.00" in out

    code, out, _ = eval_run(checkout, capsys, "decisions", "--plan")
    assert "5 already cached, 0 new" in out

    saved = sorted(checkout.passes.glob("*-decisions.json"))[-1]
    code, out, _ = eval_run(checkout, capsys, "report", "--record", str(saved))
    assert code == 0 and "recorded in" in out
    code, out, _ = eval_run(checkout, capsys, "report", "--record", str(saved))
    assert "against the row before" in out
    (recorded,) = [p for p in checkout.replay.glob("*.jsonl")] or [None]
    text = recorded.read_text(encoding="utf-8")
    assert "Organise" not in text and POPUP not in text and "bookmarks bar" not in text and "coldplay" not in text
    assert "t1" in eval_run(checkout, capsys, "report")[1]

    assert eval_run(checkout, capsys, "batch", "iteration", "--note", "first")[1].endswith("iteration 1 of 2\n")
    assert eval_run(checkout, capsys, "batch", "close")[1].startswith("closed batch t1")
    assert eval_run(checkout, capsys, "batch", "status")[1] == "no batch is open\n"


def test_a_pass_the_service_never_answered_is_not_saved_as_a_pass(checkout, capsys, monkeypatch):
    def gone(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"message": "No endpoints found."}})

    real = decisions.EvalClient
    monkeypatch.setattr(decisions, "EvalClient", lambda *a, **k: real(*a, **k, transport=httpx.MockTransport(gone)))
    eval_run(checkout, capsys, "harvest")
    eval_run(checkout, capsys, "batch", "open", "--cap", "1", "--iterations", "1")

    code, _, err = eval_run(checkout, capsys, "decisions")

    assert code == 2 and "nothing was answered, so no pass was saved" in err and "404" in err
    assert not list(checkout.passes.glob("*-decisions.json")) and not checkout.replay.exists()


def test_a_batch_is_opened_only_with_the_cap_and_iterations_the_user_approved(checkout, capsys):
    code, _, err = eval_run(checkout, capsys, "batch", "open", "--cap", "4")
    assert code == 2 and "--iterations" in err
    assert not checkout.ledger.exists()


# ------------------------------------------------------------------ the digest, on folders written by hand


def hand_run(
    home: Home, name: str, summary: dict, steps: dict[int, dict] | None = None, reviews: dict[int, list] | None = None
) -> None:
    folder = home.runs / name
    folder.mkdir(parents=True)
    (folder / "run.json").write_text(json.dumps(summary), encoding="utf-8")
    for n, answers in (steps or {}).items():
        (folder / f"step-{n:03d}-answers.json").write_text(json.dumps(answers), encoding="utf-8")
    for n, records in (reviews or {}).items():
        (folder / f"step-{n:03d}-review.json").write_text(json.dumps(records), encoding="utf-8")


def test_the_digest_counts_runs_by_outcome_and_lists_the_first_stop_of_each_that_fell_short(tmp_path):
    home = Home(tmp_path)
    models = {"decisions": "vendor/model"}
    hand_run(
        home, "r1", {"act": True, "outcome": "done", "goal_achieved": True, "models": models, "steps_taken": 3, "seconds": 9.0}
    )
    hand_run(
        home,
        "r2",
        {
            "act": True,
            "outcome": "stopped",
            "goal_achieved": False,
            "goal": "a goal",
            "models": models,
            "steps_taken": 5,
            "seconds": 20.0,
            "cost": 0.02,
        },
        steps={
            1: {
                "kind": "click_item",
                "kind_confidence": 0.9,
                "item": 0,
                "item_confidence": 0.2,
                "items": [{"index": 0, "text": "Buy"}],
                "app": "Chrome",
            }
        },
        reviews={2: [{"outcome": "low_confidence", "handed_back": True}]},
    )
    hand_run(home, "r3", {"act": False, "outcome": "dry run", "models": models})  # took no action: not counted
    hand_run(
        home,
        "r4",
        {"act": True, "outcome": "aborted (Ctrl-C)", "goal_achieved": None, "models": models, "reviews": 0},
        reviews={1: [{"outcome": "stall"}]},
    )
    (home.runs / "r5").mkdir()  # no run.json: skipped

    result = digest.digest(home)

    assert result["outcomes"] == {"done / achieved=True": 1, "stopped / achieved=False": 1, "aborted / achieved=None": 1}
    assert result["stops"] == {"low_confidence": 1, "stall": 1} and result["sent_back"] == {"low_confidence": 1}
    assert result["models"]["vendor/model"]["runs"] == 3 and result["models"]["vendor/model"]["achieved"] == 1
    (candidate,) = result["candidates"]  # r4 was the user's own stop, r1 succeeded
    assert candidate["run"] == "r2" and candidate["decision"]["id"] == "r2/001" and candidate["decision"]["item_text"] == "Buy"
    text = digest.render(result)
    assert "r2/001  low_confidence  click_item (kind 0.90, item 0.20) -> 'Buy'" in text
    assert "BY DECISION MODEL" in text and "vendor/model: 3 runs, 1 of 2 judged achieved" in text

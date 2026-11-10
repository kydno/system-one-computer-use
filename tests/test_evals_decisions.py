"""The eval kit's decision passes, its cache, and the budget that stands in front of every request."""

from __future__ import annotations

import json

import httpx
import pytest
from evals_support import echo_factory, home_with, run_form, run_popup
from world import FakeTypeSafe

from typesafe_computer_use.decisions import Choice, Endpoint, is_settled
from typesafe_computer_use.evals import budget, cases, decisions, report, size
from typesafe_computer_use.evals.store import Home

WHERE = Endpoint("openrouter", "https://decisions.example.com/v1/decisions", "key", "vendor/model")
QUESTIONS = {"q": Choice(criteria={"a": "the first", "b": "the second"})}
REPLY = {
    "model": "vendor/model-1",
    "usage": {"input_tokens": 10, "output_tokens": 2, "cost": 0.003},
    "answers": {"q": {"type": "choice", "choice": "a", "confidence": 0.9, "probabilities": {"a": 0.9, "b": 0.1}}},
}


def client(tmp_path, repeat: int, ledger, sent: list):
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=REPLY)

    return decisions.EvalClient(WHERE, tmp_path / "cache", repeat, ledger, transport=httpx.MockTransport(handler))


def open_ledger(tmp_path, cap: float = 0.05) -> budget.Ledger:
    ledger = budget.Ledger(tmp_path / "ledger.jsonl")
    ledger.open(cap, 3)
    return ledger


def test_a_request_already_asked_is_answered_from_the_cache_and_costs_nothing(tmp_path):
    ledger, sent = open_ledger(tmp_path), []

    with client(tmp_path, 0, ledger, sent) as first:
        assert first.system_one({"goal": "g"}, QUESTIONS).answers["q"].choice == "a"
    with client(tmp_path, 0, ledger, sent) as again:
        assert again.system_one({"goal": "g"}, QUESTIONS).answers["q"].choice == "a"
    with client(tmp_path, 1, ledger, sent) as other_sample:
        other_sample.system_one({"goal": "g"}, QUESTIONS)
    with client(tmp_path, 0, ledger, sent) as changed:
        changed.system_one({"goal": "a different state"}, QUESTIONS)

    assert len(sent) == 3  # the repeat and the changed state are new requests; the replay is not
    assert (first.sent, first.cached, again.sent, again.cached) == (1, 0, 0, 1)
    assert ledger.current().spent_usd == pytest.approx(0.009)


def test_no_request_is_sent_without_an_open_batch_or_once_its_cap_is_spent(tmp_path):
    sent: list = []
    with (
        client(tmp_path, 0, budget.Ledger(tmp_path / "none.jsonl"), sent) as unfunded,
        pytest.raises(budget.BudgetError, match="no batch"),
    ):
        unfunded.system_one({"goal": "g"}, QUESTIONS)

    spent = open_ledger(tmp_path / "spent", cap=0.012)  # one call leaves less than the reserve
    with client(tmp_path, 0, spent, sent) as paying:
        paying.system_one({"goal": "g"}, QUESTIONS)
        with pytest.raises(budget.BudgetError, match="cap is spent"):
            paying.system_one({"goal": "again"}, QUESTIONS)

    assert len(sent) == 1


def test_a_batch_counts_iterations_and_closes(tmp_path):
    ledger = budget.Ledger(tmp_path / "ledger.jsonl")
    with pytest.raises(budget.BudgetError):
        ledger.iteration()
    ledger.open(4.0, 2, name="first")
    with pytest.raises(budget.BudgetError, match="still open"):
        ledger.open(1.0, 1)
    ledger.iteration("a")
    ledger.spend(1.5, "decisions")
    assert ledger.current().line() == "batch first: $1.5000 of $4.00 spent, iteration 1 of 2"
    ledger.iteration("b")
    with pytest.raises(budget.BudgetError, match="no iteration is left"):
        ledger.iteration("c")
    assert ledger.close().name == "first" and ledger.current() is None
    assert ledger.open(2.0, 1).name == "b2"


def frozen(monkeypatch, tmp_path) -> list[cases.Case]:
    """Both simulated runs, filed under run names of their own as a checkout files them."""
    run_popup(monkeypatch, tmp_path / "a")
    run_form(monkeypatch, tmp_path / "b")
    home = home_with(tmp_path / "home", (tmp_path / "a", "20261101-000000"), (tmp_path / "b", "20261101-000100"))
    cases.harvest(home)
    return cases.load_cases(home)


def selected(found: list[cases.Case], labels: dict | None = None):
    return cases.select(found, labels or {}, "labeled")


def test_a_classifier_that_picks_what_the_run_picked_agrees_with_every_silver_label(monkeypatch, tmp_path):
    found = frozen(monkeypatch, tmp_path)

    rows, used, stopped = decisions.run_pass(selected(found), echo_factory(found), repeats=2)
    summary = decisions.summarize(rows, 2, 0.4)

    assert stopped is None and len(rows) == 2 * len(found)
    assert summary["silver"] == {
        "cases": 5,
        "agree": 1.0,
        "cases_mostly_right": 5,
        "right_below_floor": 0,
        "wrong_above_floor": 0,
        "no_decision": 0,
    }
    assert summary["same_pick_every_repeat"] == 1.0
    assert decisions.misses(rows) == [] and used["sent"] == 0


def test_a_classifier_that_picks_otherwise_is_counted_wrong_and_surely_so(monkeypatch, tmp_path):
    found = frozen(monkeypatch, tmp_path)
    always_scroll = lambda repeat: FakeTypeSafe(lambda state, questions: ("scroll_down", None))  # noqa: E731

    rows, _, _ = decisions.run_pass(selected(found), always_scroll, repeats=1)
    summary = decisions.summarize(rows, 1, 0.4)

    assert summary["silver"]["agree"] == 0.0 and summary["silver"]["wrong_above_floor"] == 5
    assert decisions.misses(rows, 2)[0]["picked"] == {"kind": "scroll_down"}
    assert summary["kinds_picked"] == {"scroll_down": 5}


def test_a_gold_label_decides_the_score_and_an_unsure_right_pick_is_counted_below_the_floor(monkeypatch, tmp_path):
    found = frozen(monkeypatch, tmp_path)
    first = found[0]
    gold = {first.id: {"kind": "click_item", "item": str(first.picked["item"]), "item_text": "Organise"}}

    def unsure(repeat: int):
        remaining = iter(selected(found, gold))

        def policy(state, questions):
            _, want, _ = next(remaining)
            return want["kind"], want.get("item_text"), 0.2  # right, and only 0.2 sure

        return FakeTypeSafe(policy)

    rows, _, _ = decisions.run_pass(selected(found, gold), unsure, repeats=1)
    summary = decisions.summarize(rows, 1, 0.4)

    assert summary["gold"]["cases"] == 1 and summary["gold"]["agree"] == 1.0 and summary["gold"]["right_below_floor"] == 1


def test_a_pass_stops_when_the_budget_does_and_keeps_what_it_has(monkeypatch, tmp_path):
    found = frozen(monkeypatch, tmp_path)
    ledger = open_ledger(tmp_path, cap=0.05)

    def factory(repeat: int):
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            names = body["questions"]
            reply = {
                **REPLY,
                "answers": {
                    n: {"type": "choice", "choice": next(iter(q["criteria"])), "confidence": 0.9, "probabilities": {}}
                    for n, q in names.items()
                },
            }
            reply["usage"] = {**REPLY["usage"], "cost": 0.02}
            return httpx.Response(200, json=reply)

        return decisions.EvalClient(WHERE, tmp_path / "cache", repeat, ledger, transport=httpx.MockTransport(handler))

    rows, used, stopped = decisions.run_pass(selected(found), factory, repeats=1)

    assert stopped is not None and "cap is spent" in stopped
    assert 0 < len(rows) < len(found) and used["sent"] == len(rows)


def test_a_plan_counts_what_the_cache_holds_before_anything_is_sent(monkeypatch, tmp_path):
    found = frozen(monkeypatch, tmp_path)
    cache = tmp_path / "cache"
    chosen = selected(found)

    assert decisions.plan(chosen, "vendor/model", cache, 2) == {"asks": 10, "cached": 0, "new": 10}

    state, questions = cases.request(chosen[0][0])
    body = {
        "model": "vendor/model",
        "state": state,
        "questions": {n: q.wire() for n, q in questions.items() if not is_settled(q)},
    }
    cache.mkdir()
    (cache / f"{decisions.cache_key(body, 1)}.json").write_text("{}", encoding="utf-8")

    assert decisions.plan(chosen, "vendor/model", cache, 2) == {"asks": 10, "cached": 1, "new": 9}


def test_size_is_measured_against_a_saved_baseline(monkeypatch, tmp_path):
    found = frozen(monkeypatch, tmp_path)
    monkeypatch.setattr(size, "git_state", lambda root: {"git_commit": "abc", "git_dirty": False})
    home = Home(tmp_path / "home")

    per_case = size.measure(found)
    size.save_baseline(home, per_case)
    smaller = {i: {**parts, "total": parts["total"] // 2} for i, parts in per_case.items()}
    delta = size.against(smaller, size.load_baseline(home)["per_case"])

    assert delta["total"]["change_pct"] == pytest.approx(-50.0, abs=0.1) and delta["state"]["change_pct"] == 0.0
    assert size.aggregate(per_case)["total"]["mean"] == round(sum(p["total"] for p in per_case.values()) / len(per_case))


def test_a_recorded_row_holds_numbers_and_model_ids_and_no_text(monkeypatch, tmp_path):
    found = frozen(monkeypatch, tmp_path)
    monkeypatch.setattr(report, "git_state", lambda root: {"git_commit": "abc", "git_dirty": True})
    home = Home(tmp_path / "home")
    rows, _, _ = decisions.run_pass(selected(found), echo_factory(found), repeats=1)
    summary = decisions.summarize(rows, 1, 0.4)

    path = report.record(home, report.row(home, "decisions", summary, {"configured": "vendor/model"}, "b1"))

    text = path.read_text(encoding="utf-8")
    assert "Organise" not in text and "20261101" not in text and "coldplay" not in text
    (saved,) = report.rows(home, "decisions")
    assert saved["git_dirty"] is True and saved["models"] == {"configured": "vendor/model"}
    worse = {**saved, "silver": {**saved["silver"], "agree": 0.5}}
    assert report.compare(saved, worse) == ["  silver.agree: 1.0 -> 0.5 (-50.0%)"]


def answering(tmp_path, ledger, reply):
    """A client factory whose service answers every request with `reply()`."""

    def factory(repeat: int):
        return decisions.EvalClient(
            WHERE, tmp_path / "cache", repeat, ledger, transport=httpx.MockTransport(lambda request: reply(request))
        )

    return factory


def test_a_service_that_answers_nothing_stops_the_pass_after_a_few_asks_and_charges_nothing(monkeypatch, tmp_path):
    found = frozen(monkeypatch, tmp_path)
    ledger = open_ledger(tmp_path)
    gone = lambda request: httpx.Response(404, json={"error": {"message": "No endpoints found for vendor/model."}})  # noqa: E731

    rows, used, stopped = decisions.run_pass(selected(found), answering(tmp_path, ledger, gone), repeats=3)

    assert len(rows) == decisions.FAILURE_STREAK and all("404" in r["error"] for r in rows)
    assert stopped is not None and f"{decisions.FAILURE_STREAK} requests in a row got no answer" in stopped
    assert used["sent"] == 0 and ledger.current().spent_usd == 0  # nothing was answered, so nothing was charged


def test_a_refusal_is_the_models_answer_and_does_not_stop_the_pass(monkeypatch, tmp_path):
    found = frozen(monkeypatch, tmp_path)

    def refuses(request: httpx.Request) -> httpx.Response:
        asked = json.loads(request.content)["questions"]
        answers = {name: {"type": "refusal", "reason": "cannot tell"} for name in asked}
        return httpx.Response(200, json={**REPLY, "answers": answers})

    rows, _, stopped = decisions.run_pass(selected(found), answering(tmp_path, open_ledger(tmp_path), refuses), repeats=2)

    assert stopped is None and len(rows) == 2 * len(found) and all("refused" in r["error"] for r in rows)


def test_one_good_answer_between_failures_starts_the_count_again(monkeypatch, tmp_path):
    found = frozen(monkeypatch, tmp_path)
    calls = iter(range(100))

    def flaky(request: httpx.Request) -> httpx.Response:
        if next(calls) % (decisions.FAILURE_STREAK) == decisions.FAILURE_STREAK - 1:
            asked = json.loads(request.content)["questions"]
            answers = {
                n: {"type": "choice", "choice": next(iter(q["criteria"])), "confidence": 0.9, "probabilities": {}}
                for n, q in asked.items()
            }
            return httpx.Response(200, json={**REPLY, "answers": answers})
        return httpx.Response(404, json={})  # not retried, as a 503 would be

    rows, _, stopped = decisions.run_pass(selected(found), answering(tmp_path, open_ledger(tmp_path), flaky), repeats=2)

    assert stopped is None and len(rows) == 2 * len(found)

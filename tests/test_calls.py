import json
from types import SimpleNamespace

import pytest
from world import FakeWriter, Page, World, drive, scripted

from typesafe_computer_use.calls import Calls, MeteredClassifier, MeteredWriter, Usage, reviewing
from typesafe_computer_use.config import answer_model, writer_model
from typesafe_computer_use.decisions import DecisionError


def test_no_request_yet_has_no_share():
    calls = Calls()

    assert calls.share("classifier") is None
    assert calls.summary()["writer"] == {"calls": 0, "share": None, "seconds": 0.0}
    assert calls.line() == "calls: classifier 0 (0%, 0.0s)  writer 0 (0%, 0.0s)"


def test_each_client_counts_its_own_requests_and_passes_them_through():
    calls = Calls()
    classifier = MeteredClassifier(SimpleNamespace(system_one=lambda **request: request), calls)
    writer = MeteredWriter(SimpleNamespace(messages=SimpleNamespace(create=lambda **request: request)), calls)

    for _ in range(3):
        assert classifier.system_one(state={}, questions={}) == {"state": {}, "questions": {}}
    assert writer.messages.create(model="m") == {"model": "m"}

    assert calls.count == {"classifier": 3, "writer": 1}
    assert calls.share("classifier") == 0.75
    assert calls.line().startswith("calls: classifier 3 (75%, ")
    # Neither reply reports usage or, for the classifier, a model: each is still a request, with zero tokens.
    assert calls.usage == {"classifier": Usage(requests=3), "m": Usage(requests=1)}


def test_a_request_that_fails_was_still_made():
    calls = Calls()

    def refuse(**request):
        raise RuntimeError("no")

    writer = MeteredWriter(SimpleNamespace(messages=SimpleNamespace(create=refuse)), calls)

    with pytest.raises(RuntimeError):
        writer.messages.create(model="m")
    assert calls.count["writer"] == 1
    assert calls.usage == {}  # no reply, so no tokens reported


def test_the_classifier_counts_tokens_under_the_model_its_reply_names():
    calls = Calls()
    replies = iter(
        [
            SimpleNamespace(model="ts-small", usage=SimpleNamespace(input_tokens=900, output_tokens=4)),
            SimpleNamespace(model="ts-small", usage=SimpleNamespace(input_tokens=None, output_tokens=None)),
            SimpleNamespace(model="ts-large", usage=SimpleNamespace(input_tokens=2000, output_tokens=6)),
        ]
    )
    classifier = MeteredClassifier(SimpleNamespace(system_one=lambda **request: next(replies)), calls)

    for _ in range(3):
        classifier.system_one(state={}, questions={})

    assert calls.usage == {
        "ts-small": Usage(requests=2, input_tokens=900, output_tokens=4),
        "ts-large": Usage(requests=1, input_tokens=2000, output_tokens=6),
    }
    assert calls.count == {"classifier": 3, "writer": 0}


def test_the_writer_counts_cache_reads_apart_and_cache_writes_as_uncached_input():
    calls = Calls()
    usage = SimpleNamespace(input_tokens=50, cache_creation_input_tokens=1000, cache_read_input_tokens=3000, output_tokens=80)
    client = SimpleNamespace(messages=SimpleNamespace(create=lambda **request: SimpleNamespace(usage=usage)))
    writer = MeteredWriter(client, calls)

    writer.messages.create(model="writer-model")
    writer.messages.create(model="answer-model")
    writer.messages.create(model="answer-model")

    assert calls.tokens() == {
        "writer-model": {"requests": 1, "input_tokens": 1050, "cached_input_tokens": 3000, "output_tokens": 80, "cost": None},
        "answer-model": {"requests": 2, "input_tokens": 2100, "cached_input_tokens": 6000, "output_tokens": 160, "cost": None},
    }
    assert calls.cost() is None  # Anthropic reports no cost, so neither the log nor run.json makes one up
    assert "cost" not in calls.line()


def test_openrouter_costs_add_up_per_model_and_over_the_run():
    calls = Calls()
    decisions = iter(
        [
            SimpleNamespace(model="jev", usage=SimpleNamespace(input_tokens=900, output_tokens=4, cost=0.0002)),
            SimpleNamespace(model="jev", usage=SimpleNamespace(input_tokens=900, output_tokens=4, cost=None)),
            SimpleNamespace(model="jev", usage=SimpleNamespace(input_tokens=900, output_tokens=4, cost=0.0003)),
        ]
    )
    classifier = MeteredClassifier(SimpleNamespace(system_one=lambda **request: next(decisions)), calls)
    usage = SimpleNamespace(input_tokens=500, output_tokens=60, cost=0.0125)
    writer = MeteredWriter(
        SimpleNamespace(messages=SimpleNamespace(create=lambda **request: SimpleNamespace(usage=usage))), calls
    )

    for _ in range(3):
        classifier.system_one(state={}, questions={})
    writer.messages.create(model="answer-model")

    assert calls.usage["jev"].cost == pytest.approx(0.0005)
    assert calls.usage["answer-model"].cost == pytest.approx(0.0125)
    assert calls.cost() == pytest.approx(0.013)
    assert calls.line().endswith("  cost $0.0130")


def test_a_decision_reply_billed_then_refused_still_counts_its_cost():
    """A reply that refused one question was billed for all of them; the run's cost said nothing of it."""
    calls = Calls()

    def refused(**request):
        error = DecisionError("the model refused 'item'")
        error.reply = SimpleNamespace(model="jev", usage=SimpleNamespace(input_tokens=900, output_tokens=4, cost=0.0004))
        raise error

    classifier = MeteredClassifier(SimpleNamespace(system_one=refused), calls)

    with pytest.raises(DecisionError):
        classifier.system_one(state={}, questions={})
    assert calls.count["classifier"] == 1
    assert calls.usage["jev"] == Usage(requests=1, input_tokens=900, output_tokens=4, cost=0.0004)
    assert calls.cost() == pytest.approx(0.0004)


def test_each_reply_is_counted_under_the_role_that_asked_for_it():
    calls = Calls()
    classifier = MeteredClassifier(
        SimpleNamespace(system_one=lambda **request: SimpleNamespace(model="jev", usage=SimpleNamespace(cost=0.001))), calls
    )
    usage = SimpleNamespace(input_tokens=10, output_tokens=2, cost=0.01)
    writer = MeteredWriter(
        SimpleNamespace(messages=SimpleNamespace(create=lambda **request: SimpleNamespace(usage=usage))), calls
    )

    classifier.system_one(state={}, questions={})
    writer.messages.create(model="same-model")  # a field fill
    with reviewing():
        writer.messages.create(model="same-model")  # a review, by the same model
    writer.messages.create(model="same-model")

    roles = calls.by_role()
    assert list(roles) == ["decision", "reviewer", "writer"]
    assert roles["decision"]["jev"]["cost"] == pytest.approx(0.001)
    assert roles["reviewer"]["same-model"]["requests"] == 1
    assert roles["writer"]["same-model"]["requests"] == 2 and roles["writer"]["same-model"]["cost"] == pytest.approx(0.02)


class CountingWriter(FakeWriter):
    """The scenario writer, with Anthropic usage on every reply."""

    def _create(self, **request):
        reply = super()._create(**request)
        reply.usage = SimpleNamespace(input_tokens=700, cache_read_input_tokens=300, output_tokens=40)
        return reply


def test_run_json_shows_tokens_per_model_and_the_calls_line_is_unchanged(monkeypatch, tmp_path):
    world = World([Page(name="done", items=["Order 4821"], url="https://example.com/done")])
    writer = CountingWriter()

    drive(world, scripted(("done", None)), monkeypatch=monkeypatch, tmp_path=tmp_path, writer=writer)

    run = json.loads((tmp_path / "run" / "run.json").read_text())
    (model,) = {request["model"] for request in writer.requests}
    assert run["usage"] == {
        "classifier": {
            "requests": 2,
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "cost": None,
        },  # the goal, then the step
        model: {
            "requests": len(writer.requests),
            "input_tokens": 700,
            "cached_input_tokens": 300,
            "output_tokens": 40,
            "cost": None,
        },
    }
    assert run["cost"] is None
    # The one writer call was the review of the stop: the answer model's, under the reviewer.
    assert set(run["usage_by_role"]) == {"decision", "reviewer"}
    assert run["usage_by_role"]["reviewer"][model]["requests"] == len(writer.requests)
    assert run["ended_at"]
    assert run["calls"]["classifier"]["calls"] == 2
    log = (tmp_path / "run" / "run.log").read_text()
    assert "calls: classifier 2 (67%, " in log and "writer 1 (33%, " in log


def test_the_run_folder_names_the_models_asked_even_when_none_replied(monkeypatch, tmp_path):
    """Tokens name only the models that replied; a run whose every decision was refused still says which was asked."""
    world = World([Page(name="home", items=["Grant access"], url="https://example.com/")])

    def refused(state: dict, questions: dict) -> tuple:
        raise DecisionError('openrouter answered 502: OpenAI refused to answer question "item"')

    drive(world, refused, monkeypatch=monkeypatch, tmp_path=tmp_path, writer=CountingWriter())

    run = json.loads((tmp_path / "run" / "run.json").read_text())
    assert run["outcome"] == "no decision"
    assert run["models"] == {"decisions": "fake/decisions", "writer": writer_model(), "answer": answer_model()}
    assert "fake/decisions" not in run["usage"]
    log = (tmp_path / "run" / "run.log").read_text()
    assert f"models: decisions fake/decisions, writer {writer_model()}, answer {answer_model()}" in log

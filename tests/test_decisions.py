"""The decision client, against a fake OpenRouter or TypeSafe served by httpx's mock transport.

Nothing here leaves the process: every request goes to a handler that records it and answers the
way the Decisions API does.
"""

from __future__ import annotations

import json

import httpx
import pytest
from world import FakeWriter, Page, World, drive

from typesafe_computer_use import decisions
from typesafe_computer_use.config import DEFAULT_OPENROUTER_DECISION_MODEL, OPENROUTER_DECISIONS_URL
from typesafe_computer_use.decisions import (
    Choice,
    ChoiceAnswer,
    DecisionClient,
    DecisionError,
    Endpoint,
    Noul,
    NoulAnswer,
    Score,
    ScoreAnswer,
    endpoint,
)
from typesafe_computer_use.runner import STOPPED

DECISION_ENV = (
    "OPENROUTER_API_KEY",
    "TYPESAFE_API_KEY",
    "TYPESAFE_BASE_URL",
    "TYPESAFE_DEFAULT_MODEL",
    "CLICKER_DECISION_PROVIDER",
    "CLICKER_DECISION_MODEL",
)
# The decision models OpenRouter serves under the one URL; only `model` differs between them.
OPENROUTER_MODELS = ("~typesafe/jev-latest", "inception/mercury-decide", "openai/gpt-6-luna-decisions")
OPENROUTER = Endpoint("openrouter", OPENROUTER_DECISIONS_URL, "sk-or-test", DEFAULT_OPENROUTER_DECISION_MODEL)
QUESTIONS = {
    "kind": Choice(instructions="Which action?", criteria={"click": "click it", "wait": "wait"}),
    "ok": Noul(instructions="Is it done?", criteria={"true": "yes", "false": "no"}),
    "urgency": Score(instructions="How urgent?", criteria=["later", "now"]),
}
ANSWERS = {
    "kind": {"type": "choice", "choice": "click", "probabilities": {"click": 0.8, "wait": 0.2}, "confidence": 0.7},
    "ok": {"type": "noul", "noul": 0.9},
    "urgency": {
        "type": "score",
        "score": 0.8,
        "legend": {"0": "later", "1": "now"},
        "probabilities": {"0": 0.2, "1": 0.8},
        "confidence": 0.6,
    },
}


@pytest.fixture
def decision_env(monkeypatch):
    for name in DECISION_ENV:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(decisions.time, "sleep", lambda seconds: None)


class Service:
    """Records each request and answers with the next scripted reply: a dict of answers, or a
    (status, body) pair."""

    def __init__(self, *replies):
        self.replies = list(replies) or [ANSWERS]
        self.seen: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, tuple):
            status, body = reply
            return httpx.Response(status, json=body)
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": f"{body['model'].lstrip('~')}-20261001",
                "answers": reply,
                "usage": {"input_tokens": 476, "output_tokens": 70, "cost": 2e-05},
            },
        )

    def client(self, where: Endpoint = OPENROUTER) -> DecisionClient:
        return DecisionClient(where, transport=httpx.MockTransport(self))


def test_openrouter_is_the_endpoint_when_its_key_is_set(decision_env):
    decision_env.setenv("OPENROUTER_API_KEY", "sk-or-test")
    decision_env.setenv("TYPESAFE_API_KEY", "ts-test")

    where = endpoint()

    assert (where.provider, where.url, where.key, where.model) == (
        "openrouter",
        "https://openrouter.ai/api/alpha/decisions",
        "sk-or-test",
        "~typesafe/jev-latest",
    )
    assert "sk-or-test" not in repr(where)


@pytest.mark.parametrize("model", OPENROUTER_MODELS)
def test_any_openrouter_decision_model_can_be_named(decision_env, model):
    decision_env.setenv("OPENROUTER_API_KEY", "sk-or-test")
    decision_env.setenv("CLICKER_DECISION_MODEL", model)

    assert endpoint().model == model


def test_typesafe_serves_when_only_its_key_is_set_or_when_asked(decision_env):
    decision_env.setenv("TYPESAFE_API_KEY", "ts-test")
    assert endpoint() == Endpoint("typesafe", "https://api.typesafe.ai/v1/systemone", "ts-test", "jev-latest")

    decision_env.setenv("OPENROUTER_API_KEY", "sk-or-test")
    decision_env.setenv("CLICKER_DECISION_PROVIDER", "typesafe")
    decision_env.setenv("TYPESAFE_BASE_URL", "https://typesafe.example/")
    decision_env.setenv("TYPESAFE_DEFAULT_MODEL", "jev-1.14")
    assert endpoint() == Endpoint("typesafe", "https://typesafe.example/v1/systemone", "ts-test", "jev-1.14")


def test_no_key_or_a_wrong_provider_stops_before_any_request(decision_env):
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY or TYPESAFE_API_KEY"):
        endpoint()
    decision_env.setenv("CLICKER_DECISION_PROVIDER", "typesafe")
    decision_env.setenv("OPENROUTER_API_KEY", "sk-or-test")
    with pytest.raises(ValueError, match="needs TYPESAFE_API_KEY"):
        endpoint()
    decision_env.setenv("CLICKER_DECISION_PROVIDER", "openai")
    with pytest.raises(ValueError, match="must be one of openrouter, typesafe"):
        endpoint()


@pytest.mark.parametrize("model", OPENROUTER_MODELS)
def test_a_request_carries_the_typesafe_schema_and_reads_every_answer(model):
    service = Service()

    reply = service.client().system_one(state={"goal": "g"}, questions=QUESTIONS, model=model)

    (request,) = service.seen
    assert str(request.url) == "https://openrouter.ai/api/alpha/decisions"
    assert request.headers["authorization"] == "Bearer sk-or-test"
    assert json.loads(request.content) == {
        "model": model,
        "state": {"goal": "g"},
        "questions": {
            "kind": {"type": "choice", "instructions": "Which action?", "criteria": {"click": "click it", "wait": "wait"}},
            "ok": {"type": "noul", "instructions": "Is it done?", "criteria": {"true": "yes", "false": "no"}},
            "urgency": {"type": "score", "instructions": "How urgent?", "criteria": ["later", "now"]},
        },
    }
    assert reply.answers == {
        "kind": ChoiceAnswer(choice="click", confidence=0.7, probabilities={"click": 0.8, "wait": 0.2}),
        "ok": NoulAnswer(noul=0.9),
        "urgency": ScoreAnswer(score=0.8, confidence=0.6, legend={"0": "later", "1": "now"}, probabilities={"0": 0.2, "1": 0.8}),
    }
    assert reply.model == f"{model.lstrip('~')}-20261001"
    assert (reply.usage.input_tokens, reply.usage.output_tokens, reply.usage.cost) == (476, 70, 2e-05)


def test_the_endpoint_model_is_asked_unless_the_call_names_one():
    service = Service({"ok": {"type": "noul", "noul": 0.1}})

    service.client().system_one(state="s", questions={"ok": Noul()})

    assert json.loads(service.seen[0].content) == {
        "model": "~typesafe/jev-latest",
        "state": "s",
        "questions": {"ok": {"type": "noul"}},
    }


def test_a_choice_without_confidence_takes_its_own_probability():
    service = Service({"kind": {"type": "choice", "choice": "wait", "probabilities": {"click": 0.35, "wait": 0.65}}})

    answer = service.client().system_one(state="s", questions={"kind": QUESTIONS["kind"]}).answers["kind"]

    assert answer.confidence == 0.65


@pytest.mark.parametrize(
    "answers",
    [
        {"kind": {"type": "refusal", "reason": "policy"}},  # Luna, answered natively
        {"kind": {"type": "choice", "choice": "scroll", "confidence": 0.9}},  # a label it was not offered
        {},  # a question skipped
        {"kind": {"type": "noul", "noul": 0.5}},  # the wrong kind of answer
        {"kind": {"type": "choice", "choice": "click", "probabilities": "?", "confidence": 0.9}},
    ],
)
def test_an_answer_that_is_not_one_is_a_decision_error(answers):
    with pytest.raises(DecisionError):
        Service(answers).client().system_one(state="s", questions={"kind": QUESTIONS["kind"]})


def test_an_overloaded_service_is_asked_again():
    service = Service((429, {"error": "slow down"}), (529, {"error": "overloaded"}), ANSWERS)

    reply = service.client().system_one(state="s", questions=QUESTIONS)

    assert len(service.seen) == 3
    assert reply.answers["ok"] == NoulAnswer(noul=0.9)


def test_a_refused_request_fails_after_its_retries():
    # OpenRouter answers a request Luna refuses any part of with a 502 for the whole of it.
    service = Service((502, {"error": {"message": "upstream refused"}}))

    with pytest.raises(DecisionError, match="502"):
        service.client().system_one(state="s", questions=QUESTIONS)
    assert len(service.seen) == decisions.MAX_RETRIES + 1


def test_a_bad_key_is_not_retried():
    service = Service((401, {"error": "bad key"}))

    with pytest.raises(DecisionError, match="401"):
        service.client().system_one(state="s", questions=QUESTIONS)
    assert len(service.seen) == 1


def test_a_step_without_a_decision_hands_the_run_to_the_writer(monkeypatch, tmp_path):
    world = World([Page(name="home", items=["Tickets", "About"], url="https://example.com/")])

    def refuses(state, questions):
        raise DecisionError("openrouter answered 502: upstream refused")

    writer = FakeWriter()
    state = drive(world, refuses, monkeypatch=monkeypatch, tmp_path=tmp_path, writer=writer)

    assert state.outcome == "no decision"
    assert world.log == []  # nothing was guessed
    assert writer.packets[0]["why_the_run_stopped"] == STOPPED["no decision"]
    assert state.answer is not None

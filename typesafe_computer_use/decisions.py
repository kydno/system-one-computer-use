"""The decision client: named questions about one state, answered with probabilities.

OpenRouter's Decisions API (`/api/alpha/decisions`) and TypeSafe's own System One API
(`/v1/systemone`) take the same body, `{model, state, questions}`, and send back the same
`{model, usage, answers}`, so one small client speaks to both. On OpenRouter any decision model
answers it, such as `~typesafe/jev-latest`, `inception/mercury-decide` or
`openai/gpt-6-luna-decisions`; only the `model` string differs. `endpoint` reads which one from the
environment.

The question and answer types mirror TypeSafe's SDK, so nothing else in the package knows which
service is on the other end. An answer is checked against the question it answers before it is
returned: a model that skips a question, refuses it, or names a label it was not offered raises
`DecisionError`, and the caller decides what a step without a decision does.
"""

from __future__ import annotations

import os
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import (
    DECISION_PROVIDERS,
    DEFAULT_OPENROUTER_DECISION_MODEL,
    DEFAULT_TYPESAFE_DECISION_MODEL,
    OPENROUTER_DECISIONS_URL,
    TYPESAFE_BASE_URL,
)

DEFAULT_TIMEOUT = 20.0  # seconds per attempt; a decision usually takes well under one
MAX_RETRIES = 2
RETRY_STATUSES = frozenset({408, 429, 500, 502, 503, 504, 529})
MAX_RETRY_WAIT = 8.0  # seconds; a longer Retry-After fails the step instead of stalling it


class DecisionError(Exception):
    """The decision model could not be reached, or did not answer every question it was asked."""


@dataclass(frozen=True)
class Choice:
    """Pick one label from `criteria`, each label mapped to what it means."""

    criteria: Mapping[str, Any]
    instructions: Any = None

    def wire(self) -> dict:
        return {"type": "choice", **_instructions(self.instructions), "criteria": dict(self.criteria)}


@dataclass(frozen=True)
class Noul:
    """A yes/no question, answered with the probability of yes."""

    instructions: Any = None
    criteria: Mapping[str, Any] | None = None  # `true` and `false`, what each outcome means

    def wire(self) -> dict:
        return {
            "type": "noul",
            **_instructions(self.instructions),
            **({"criteria": dict(self.criteria)} if self.criteria else {}),
        }


@dataclass(frozen=True)
class Score:
    """A level on an ordered rubric, lowest first, answered with the expected level."""

    criteria: list[Any]
    instructions: Any = None

    def wire(self) -> dict:
        return {"type": "score", **_instructions(self.instructions), "criteria": list(self.criteria)}


type Question = Choice | Noul | Score


@dataclass(frozen=True)
class ChoiceAnswer:
    choice: str
    confidence: float
    probabilities: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class NoulAnswer:
    noul: float  # the probability of yes


@dataclass(frozen=True)
class ScoreAnswer:
    score: float
    confidence: float
    legend: dict[str, Any] = field(default_factory=dict)
    probabilities: dict[str, float] = field(default_factory=dict)


type Answer = ChoiceAnswer | NoulAnswer | ScoreAnswer


@dataclass(frozen=True)
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost: float | None = None  # USD, when the service reports it (OpenRouter does)


@dataclass(frozen=True)
class Reply:
    model: str  # the exact build that answered, such as typesafe/jev-1.14-20261001
    usage: Usage
    answers: dict[str, Answer]


@dataclass(frozen=True)
class Endpoint:
    """Where decisions go: the service, its full request URL, its key, and the model asked."""

    provider: str
    url: str
    key: str = field(repr=False)
    model: str

    def describe(self) -> str:
        return f"{self.provider} {self.url}  model: {self.model}"


def endpoint() -> Endpoint:
    """The decision endpoint the environment configures.

    OPENROUTER_API_KEY sends decisions to OpenRouter, TYPESAFE_API_KEY to TypeSafe; with both set,
    OpenRouter, unless CLICKER_DECISION_PROVIDER names the other. CLICKER_DECISION_MODEL picks the
    model, by default `~typesafe/jev-latest` on OpenRouter and `jev-latest` on TypeSafe, where
    TYPESAFE_DEFAULT_MODEL and TYPESAFE_BASE_URL are read as TypeSafe's SDK reads them.
    Raises ValueError when no key is set for the provider.
    """
    keys = {"openrouter": _env("OPENROUTER_API_KEY"), "typesafe": _env("TYPESAFE_API_KEY")}
    chosen = (_env("CLICKER_DECISION_PROVIDER") or "").lower()
    if chosen and chosen not in DECISION_PROVIDERS:
        raise ValueError(f"CLICKER_DECISION_PROVIDER must be one of {', '.join(DECISION_PROVIDERS)}, not {chosen!r}")
    provider = chosen or next((name for name in DECISION_PROVIDERS if keys[name]), None)
    if provider is None:
        raise ValueError("no decision model: set OPENROUTER_API_KEY or TYPESAFE_API_KEY (export it or put it in .env)")
    key = keys[provider]
    if not key:
        raise ValueError(f"CLICKER_DECISION_PROVIDER={provider} needs {provider.upper()}_API_KEY")
    model = _env("CLICKER_DECISION_MODEL")
    if provider == "openrouter":
        return Endpoint(provider, OPENROUTER_DECISIONS_URL, key, model or DEFAULT_OPENROUTER_DECISION_MODEL)
    base = (_env("TYPESAFE_BASE_URL") or TYPESAFE_BASE_URL).rstrip("/")
    return Endpoint(
        provider, f"{base}/v1/systemone", key, model or _env("TYPESAFE_DEFAULT_MODEL") or DEFAULT_TYPESAFE_DECISION_MODEL
    )


class DecisionClient:
    """One HTTP client for the run. `system_one` is the only call the package makes."""

    def __init__(
        self, where: Endpoint | None = None, *, timeout: float = DEFAULT_TIMEOUT, transport: httpx.BaseTransport | None = None
    ):
        self.endpoint = where or endpoint()
        self._http = httpx.Client(
            timeout=timeout,
            transport=transport,
            headers={"Authorization": f"Bearer {self.endpoint.key}", "X-Title": "typesafe-computer-use"},
        )

    def system_one(self, state: Any, questions: Mapping[str, Question], model: str | None = None) -> Reply:
        if not questions:
            raise ValueError("a decision needs at least one question")
        body = {
            "model": model or self.endpoint.model,
            "state": state,
            "questions": {name: question.wire() for name, question in questions.items()},
        }
        data = self._post(body)
        raw = data.get("answers")
        if not isinstance(raw, dict):
            raise DecisionError(f"the reply has no answers: {str(data)[:300]}")
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        return Reply(
            model=str(data.get("model") or body["model"]),
            usage=Usage(
                input_tokens=_int(usage.get("input_tokens")),
                output_tokens=_int(usage.get("output_tokens")),
                cost=usage.get("cost") if isinstance(usage.get("cost"), int | float) else None,
            ),
            answers={name: _answer(name, question, raw.get(name)) for name, question in questions.items()},
        )

    def _post(self, body: dict) -> dict:
        for attempt in range(MAX_RETRIES + 1):
            last = attempt == MAX_RETRIES
            try:
                response = self._http.post(self.endpoint.url, json=body)
            except httpx.TransportError as e:
                if last:
                    raise DecisionError(f"{self.endpoint.provider} could not be reached: {e}") from e
                time.sleep(_backoff(attempt))
                continue
            if response.status_code in RETRY_STATUSES and not last:
                wait = _retry_after(response) or _backoff(attempt)
                if wait <= MAX_RETRY_WAIT:
                    time.sleep(wait)
                    continue
            if response.is_error:
                # OpenRouter answers a request Luna refuses any part of with a 502 for all of it.
                raise DecisionError(f"{self.endpoint.provider} answered {response.status_code}: {response.text[:300]}")
            try:
                data = response.json()
            except ValueError as e:
                raise DecisionError(f"{self.endpoint.provider} answered without JSON: {response.text[:300]!r}") from e
            if not isinstance(data, dict):
                raise DecisionError(f"{self.endpoint.provider} answered with {type(data).__name__}, not an object")
            return data
        raise AssertionError("unreachable")

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> DecisionClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _answer(name: str, question: Question, raw: Any) -> Answer:
    """One answer, checked against its question. Anything else is a step without a decision."""
    if not isinstance(raw, dict):
        raise DecisionError(f"no answer to {name!r}")
    kind = raw.get("type")
    if kind == "refusal":
        raise DecisionError(f"the model refused {name!r}: {str(raw.get('reason') or raw.get('refusal') or '')[:200]}")
    try:
        if isinstance(question, Choice):
            if kind != "choice" or raw.get("choice") not in question.criteria:
                raise DecisionError(f"the answer to {name!r} is not one of its labels: {str(raw)[:200]}")
            probabilities = {str(k): float(v) for k, v in (raw.get("probabilities") or {}).items()}
            confidence = raw.get("confidence", probabilities.get(raw["choice"]))
            if confidence is None:
                raise DecisionError(f"the answer to {name!r} has no confidence")
            return ChoiceAnswer(choice=raw["choice"], confidence=float(confidence), probabilities=probabilities)
        if isinstance(question, Noul):
            if kind != "noul":
                raise DecisionError(f"the answer to {name!r} is not a yes/no: {str(raw)[:200]}")
            return NoulAnswer(noul=float(raw["noul"]))
        if kind != "score":
            raise DecisionError(f"the answer to {name!r} is not a score: {str(raw)[:200]}")
        return ScoreAnswer(
            score=float(raw["score"]),
            confidence=float(raw.get("confidence") or 0.0),
            legend={str(k): v for k, v in (raw.get("legend") or {}).items()},
            probabilities={str(k): float(v) for k, v in (raw.get("probabilities") or {}).items()},
        )
    except (AttributeError, KeyError, TypeError, ValueError) as e:
        raise DecisionError(f"the answer to {name!r} is malformed: {str(raw)[:200]}") from e


def _instructions(instructions: Any) -> dict:
    return {} if instructions is None else {"instructions": instructions}


def _env(name: str) -> str | None:
    return (os.environ.get(name) or "").strip() or None


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _backoff(attempt: int) -> float:
    return 0.5 * 2**attempt


def _retry_after(response: httpx.Response) -> float | None:
    try:
        return float(response.headers["retry-after"])
    except (KeyError, ValueError):
        return None

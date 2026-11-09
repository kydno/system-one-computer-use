"""Count the requests, tokens and cost each model takes, at the two clients every request goes through."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from types import SimpleNamespace

CLASSIFIER = "classifier"
WRITER = "writer"
MODELS = (CLASSIFIER, WRITER)

# What each model does in the run, for what it cost: the classifier decides, the answer model
# reviews each stop, and the writer's own model fills fields and proposes URLs. The writer client
# carries both of the last two, so a review says which it is with `reviewing`.
DECISION = "decision"
REVIEWER = "reviewer"
ROLES = (DECISION, REVIEWER, WRITER)
_writer_role: ContextVar[str] = ContextVar("writer_role", default=WRITER)


@contextmanager
def reviewing() -> Iterator[None]:
    """Count the writer client's requests inside as the reviewer's, the answer model's."""
    token = _writer_role.set(REVIEWER)
    try:
        yield
    finally:
        _writer_role.reset(token)


@dataclass
class Usage:
    """The tokens one model took, over the requests that came back with a reply.

    `input_tokens` are the uncached ones, including those written to a cache; `cached_input_tokens`
    were read from one. A reply that reports no usage still counts as a request, with zero tokens.
    `cost` is in USD, summed over the replies that report one (OpenRouter's do), and None until one does.
    """

    requests: int = 0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    cost: float | None = None

    def record(
        self, input_tokens: int = 0, cached_input_tokens: int = 0, output_tokens: int = 0, cost: float | None = None
    ) -> None:
        self.requests += 1
        self.input_tokens += input_tokens
        self.cached_input_tokens += cached_input_tokens
        self.output_tokens += output_tokens
        if cost is not None:
            self.cost = (self.cost or 0.0) + cost


@dataclass
class Calls:
    """How many requests went to each model, and the seconds they took.

    The point of the design is that the classifier takes nearly all of them. This is the number
    that says whether it does: a run the writer has to steer at every turn shows up here.
    """

    count: dict[str, int] = field(default_factory=lambda: dict.fromkeys(MODELS, 0))
    seconds: dict[str, float] = field(default_factory=lambda: dict.fromkeys(MODELS, 0.0))
    usage: dict[str, Usage] = field(default_factory=dict)  # keyed by the model id each reply names
    roles: dict[str, dict[str, Usage]] = field(default_factory=dict)  # the same, under the role that asked

    @contextmanager
    def record(self, model: str) -> Iterator[None]:
        """Count one request to `model`. A request that fails was still made, so it still counts."""
        started = time.perf_counter()
        try:
            yield
        finally:
            self.count[model] += 1
            self.seconds[model] += time.perf_counter() - started

    def used(
        self,
        model: str,
        input_tokens: int = 0,
        cached_input_tokens: int = 0,
        output_tokens: int = 0,
        cost: float | None = None,
        role: str | None = None,
    ) -> None:
        """Add one reply's tokens and cost to `model`, the model id it came from, and to `role` when given."""
        self.usage.setdefault(model, Usage()).record(input_tokens, cached_input_tokens, output_tokens, cost)
        if role is not None:
            by_model = self.roles.setdefault(role, {})
            by_model.setdefault(model, Usage()).record(input_tokens, cached_input_tokens, output_tokens, cost)

    def cost(self) -> float | None:
        """The USD the run's replies reported costing, over every model; None when none reported one.

        A model whose replies report no cost (TypeSafe's, Anthropic's) adds nothing, so with one of
        those in the run this is what the rest cost, not the whole bill."""
        costs = [usage.cost for usage in self.usage.values() if usage.cost is not None]
        return round(sum(costs), 6) if costs else None

    def share(self, model: str) -> float | None:
        """The fraction of all requests that went to `model`, or None before any request."""
        total = sum(self.count.values())
        return self.count[model] / total if total else None

    def summary(self) -> dict:
        return {
            model: {
                "calls": self.count[model],
                "share": None if self.share(model) is None else round(self.share(model), 3),
                "seconds": round(self.seconds[model], 3),
            }
            for model in MODELS
        }

    def tokens(self) -> dict:
        """Tokens and cost per model id, for run.json."""
        return {model: asdict(usage) for model, usage in self.usage.items()}

    def by_role(self) -> dict:
        """Tokens and cost per model id under each role that used one, for run.json: what the menu
        bar's usage breakdown splits the bill by."""
        return {role: {model: asdict(usage) for model, usage in self.roles[role].items()} for role in ROLES if role in self.roles}

    def line(self) -> str:
        """One log line: `calls: classifier 12 (86%, 3.1s)  writer 2 (14%, 8.0s)  cost $0.0123`, the cost
        only when a reply reported one."""
        parts = [f"{model} {self.count[model]} ({(self.share(model) or 0):.0%}, {self.seconds[model]:.1f}s)" for model in MODELS]
        cost = self.cost()
        if cost is not None:
            parts.append(f"cost ${cost:.4f}")
        return "calls: " + "  ".join(parts)


class MeteredClassifier:
    """The decision client, counting each request. `system_one` is the only call the package makes.

    The reply, from OpenRouter or TypeSafe, names its `model` and reports `usage` as `input_tokens`
    and `output_tokens`, with no cached count, and OpenRouter's a `cost` too.
    """

    def __init__(self, client, calls: Calls):
        self._client = client
        self._calls = calls

    def system_one(self, **request):
        with self._calls.record(CLASSIFIER):
            try:
                reply = self._client.system_one(**request)
            except Exception as e:
                # A reply that came back and was billed, then refused a question or broke its
                # schema, is still on the bill: the client hands it over on the error.
                billed = getattr(e, "reply", None)
                if billed is not None:
                    self._record(billed, request)
                raise
        self._record(reply, request)
        return reply

    def _record(self, reply, request: dict) -> None:
        usage = getattr(reply, "usage", None)
        self._calls.used(
            _model(getattr(reply, "model", None), request.get("model"), CLASSIFIER),
            input_tokens=_tokens(usage, "input_tokens"),
            output_tokens=_tokens(usage, "output_tokens"),
            cost=_cost(usage),
            role=DECISION,
        )


class MeteredWriter:
    """The Anthropic client, counting each request. `messages.create` is the only call the package makes."""

    def __init__(self, client, calls: Calls):
        self._client = client
        self._calls = calls
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **request):
        with self._calls.record(WRITER):
            reply = self._client.messages.create(**request)
        usage = getattr(reply, "usage", None)
        self._calls.used(
            _model(request.get("model"), WRITER),
            input_tokens=_tokens(usage, "input_tokens") + _tokens(usage, "cache_creation_input_tokens"),
            cached_input_tokens=_tokens(usage, "cache_read_input_tokens"),
            output_tokens=_tokens(usage, "output_tokens"),
            cost=_cost(usage),
            role=_writer_role.get(),
        )
        return reply


def _model(*names) -> str:
    """The first name that is a model id, as a reply or a request may leave it out."""
    return next(name for name in names if isinstance(name, str) and name)


def _tokens(usage, name: str) -> int:
    """One count from a usage object, or 0 when the reply leaves it out or reports it as None."""
    count = getattr(usage, name, None)
    return count if isinstance(count, int) else 0


def _cost(usage) -> float | None:
    """The USD a reply reports costing, or None when it reports none, as Anthropic's and TypeSafe's do."""
    cost = getattr(usage, "cost", None)
    return float(cost) if isinstance(cost, int | float) and not isinstance(cost, bool) else None

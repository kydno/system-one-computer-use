"""Run tasks through the real loop on the mock OS: the oracle check, and passes that leave rows.

A task runs as a real run does: `runner.run` inside `platform_adapter.using(MockDesktop(...))`, with
the clock held at the seed's time, so the same screen builds the same request on any day. What
answers differs:

- `check` answers with the stand-ins (`stand_ins.py`) and the task's oracle. No model is asked, so
  it costs nothing; a task whose oracle fails is a broken task or a broken mock, not the agent.
- `run` answers with the real models, each reply cached by its request: a pass on unchanged code
  sends nothing, and a change pays only for the requests it changed. Every real request is charged
  to the batch the user opened (`evals/budget.py`), and the pass stops, keeping its rows, once the
  cap is spent. A cached reply keeps the tokens, cost and seconds it was recorded with, so a row
  says what the run would cost live whether or not this pass paid for it.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from .. import config, dates, decide, runner
from .. import writer as writer_module
from ..actions import Context
from ..decisions import DecisionClient, Endpoint, endpoint
from ..evals.budget import BudgetError, Ledger
from ..evals.decisions import EvalClient, cache_key
from ..evals.store import Home, checkout_root, git_state, stamp
from ..platform_adapter import using
from ..runner import RunConfig, RunState
from ..stand_ins import FakeTypeSafe, FakeWriter
from .desktop import BROWSER, MockDesktop
from .page import MockPage
from .tasks import MOCK_EMAIL as EMAIL
from .tasks import Task, oracle_policy

WRITER_ESTIMATE_USD = 0.02  # charged for a writer reply that reports no cost, so the cap still holds
PASSES = Path("benchmarks") / "mockos"
PHASES = ("capture", "ocr", "ax", "decide", "act", "settle", "total")  # the step phases a row keeps, as mean seconds
WORK = Path(".mockos")


@dataclass(frozen=True)
class Where:
    """Where a pass keeps its files, under the main checkout (`store.checkout_root`), so that the
    worktrees of one checkout share the cache."""

    root: Path

    @property
    def passes(self) -> Path:
        return self.root / PASSES

    @property
    def cache(self) -> Path:
        return self.root / WORK / "cache"

    @property
    def runs(self) -> Path:
        return self.root / WORK / "runs"

    @property
    def ledger(self) -> Path:
        return Home(self.root).ledger  # the one budget, shared with clicker-eval

    @staticmethod
    def here() -> Where:
        return Where(checkout_root())


# ----- the clock ---------------------------------------------------------------------------------


@contextmanager
def held_clock(iso: str) -> Iterator[None]:
    """Every request reads the seed's time, not today's: what 'in 3 days' counts from, and the time in
    the state the decision model and the writer read. The page shows the same time in its top bar."""
    moment = datetime.fromisoformat(iso)
    now = {"local_time": moment.strftime("%Y-%m-%d %H:%M %A"), "timezone": "UTC", "today": moment.date().isoformat()}
    with (
        mock.patch.object(decide, "now_context", lambda: now),
        mock.patch.object(writer_module, "now_context", lambda: now),
        mock.patch.object(decide, "date_hints", partial(dates.date_hints, today=moment.date())),
    ):
        yield


# ----- the cached, budgeted clients ----------------------------------------------------------------


def request_key(body: dict, repeat: int) -> str:
    return hashlib.sha256(json.dumps([body, repeat], sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


class CachedDecisions(EvalClient):
    """`EvalClient`, which caches each reply by its request and charges each real one to the budget,
    plus the seconds each reply took when it was recorded, so a cached step still says how long the
    live one waited."""

    def __init__(self, where: Endpoint, cache: Path, repeat: int, ledger, **kwargs) -> None:
        super().__init__(where, cache, repeat, ledger, **kwargs)
        self.recorded = 0.0  # seconds the replies took when they were recorded, served live or not

    def _post(self, body: dict) -> dict:
        meta = self.cache / f"{cache_key(body, self.repeat)}.seconds"
        sent, live = self.sent, self.seconds
        data = super()._post(body)
        if self.sent > sent:
            took = self.seconds - live
            meta.write_text(f"{took:.4f}", encoding="utf-8")
        else:
            try:
                took = float(meta.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                took = 0.0
        self.recorded += took
        return data


class CachedWriter:
    """The writer client behind the one call the package makes, `messages.create`, with each reply
    cached by its request (the screenshot included) and each real request charged to the budget.

    A miss with no writer to ask, or no money left, raises `BudgetError`, which ends the run and the
    pass with the rows it has."""

    def __init__(self, inner, cache: Path, repeat: int, ledger) -> None:
        self._inner = inner
        self.cache = cache / "writer"
        self.repeat = repeat
        self.ledger = ledger
        self.sent = self.cached = 0
        self.seconds = self.spent = self.recorded = 0.0
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **request):
        path = self.cache / f"{request_key(request, self.repeat)}.json"
        if path.is_file():
            try:
                saved = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                saved = None
            if isinstance(saved, dict):
                self.cached += 1
                self.recorded += float(saved.get("seconds") or 0.0)
                return _reply(saved)
        if self._inner is None:
            raise BudgetError("the writer's reply is not cached and no writer is configured to ask")
        self.ledger.require_funds()
        started = time.perf_counter()
        reply = self._inner.messages.create(**request)
        took = time.perf_counter() - started
        usage = getattr(reply, "usage", None)
        counts = {
            name: getattr(usage, name, None)
            for name in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "cost")
        }
        cost = counts["cost"] if isinstance(counts["cost"], int | float) and not isinstance(counts["cost"], bool) else None
        self.sent += 1
        self.seconds += took
        self.recorded += took
        self.spent += cost if cost is not None else WRITER_ESTIMATE_USD
        self.ledger.spend(cost if cost is not None else WRITER_ESTIMATE_USD, f"writer {request.get('model')}")
        saved = {
            "text": "".join(getattr(b, "text", "") for b in getattr(reply, "content", []) if getattr(b, "type", "") == "text"),
            "stop_reason": getattr(reply, "stop_reason", None),
            "usage": {k: v for k, v in counts.items() if isinstance(v, int | float) and not isinstance(v, bool)},
            "seconds": round(took, 4),
        }
        self.cache.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(saved), encoding="utf-8")
        return _reply(saved)


def _reply(saved: dict) -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=saved.get("text") or "")],
        stop_reason=saved.get("stop_reason"),
        usage=SimpleNamespace(**(saved.get("usage") or {})),
    )


class CachedOnly:
    """A ledger that pays for nothing: every request must be in the cache (`--cached-only`)."""

    def require_funds(self):
        raise BudgetError("--cached-only: this request is not in the cache")

    def spend(self, usd: float, what: str):
        raise BudgetError("--cached-only: nothing may be spent")


# ----- one task ----------------------------------------------------------------------------------


@dataclass
class Outcome:
    """What one run of one task came to."""

    task: Task
    repeat: int
    state: RunState | None
    final: dict | None
    answer: str | None
    score: int
    seconds: float
    folder: Path
    error: str | None = None
    calls: dict = field(default_factory=dict)  # sent, cached, spent, recorded and live seconds, per client


def run_task(
    page: MockPage,
    task: Task,
    out: Path,
    *,
    decisions: Callable[[], object],
    writer,
    ocr: str = "dom",
    latency: str = "typical",
    repeat: int = 0,
    steps: int | None = None,
) -> Outcome:
    """Load the task, run the real loop on it, and check the state it leaves."""
    page.load(task.seed, latency)
    adapter = MockDesktop(page.call, page.session.call, ocr=ocr)
    replies = list(task.replies)

    def ask(question: str) -> str:
        return replies.pop(0) if replies else ""

    apps = tuple(adapter.installed_apps())

    def ctx_factory(typesafe, history) -> Context:
        return Context(
            goal=task.goal,
            browser=BROWSER,
            email=EMAIL,
            typesafe=typesafe,
            writer=writer,
            history=history,
            ask=ask if task.replies else None,
            browsers=(),
            apps=apps,
        )

    cfg = RunConfig(goal=task.goal, out=out, act=True, steps=steps or task.steps)
    started = time.perf_counter()
    state, error = None, None
    try:
        with using(adapter), held_clock(task.seed["clock"]):
            state = runner.run(cfg, ctx_factory, decisions=decisions)
    except BudgetError as e:
        error = f"budget: {e}"
    except Exception as e:  # the run folder keeps the traceback (runner.run logs it)
        error = f"{type(e).__name__}: {e}"
    seconds = time.perf_counter() - started
    final = page.dump()
    answer = state.answer.text if state is not None and state.answer is not None else None
    claimed = state is not None and state.answer is not None and state.answer.achieved
    try:
        score = int(bool(task.check(final, answer)) and not (task.trap and claimed)) if error is None else 0
    except Exception as e:
        score, error = 0, f"the check failed: {type(e).__name__}: {e}"
    (out / "mockos.json").write_text(
        json.dumps({"task": task.id, "repeat": repeat, "score": score, "error": error, "final": final}, indent=2),
        encoding="utf-8",
    )
    return Outcome(task, repeat, state, final, answer, score, round(seconds, 3), out, error)


def oracle(page: MockPage, task: Task, out: Path, *, ocr: str = "dom", latency: str = "typical") -> Outcome:
    """Run the task's scripted solution through the real loop, with stand-ins for both models."""
    fake = FakeTypeSafe(oracle_policy(task.oracle), read_only=task.read_only, moves="moves" in task.tags)
    writer = FakeWriter(texts=list(task.writes), url=task.url, reviews=list(task.reviews))
    return run_task(page, task, out, decisions=lambda: fake, writer=writer, ocr=ocr, latency=latency)


# ----- a pass ----------------------------------------------------------------------------------------


def load_config(where: Where) -> dict:
    """The models a pass runs on: `benchmarks/mockos/config.json` when it names them, else the
    environment's, as a real run reads them. Every row records the model ids that answered."""
    path = where.passes / "config.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def decision_endpoint(settings: dict, cached_only: bool) -> Endpoint:
    """The decision endpoint, with the model the pass's config names. A pass served from the cache
    alone needs no key: the model name is all a cached request is looked up by."""
    model = settings.get("decisions")
    try:
        where = endpoint()
    except ValueError:
        if not cached_only:
            raise
        where = Endpoint("openrouter", config.OPENROUTER_DECISIONS_URL, "", model or config.DEFAULT_OPENROUTER_DECISION_MODEL)
    return Endpoint(where.provider, where.url, where.key, model or where.model)


def row(outcome: Outcome, name: str, settings: dict, page: MockPage, git: dict) -> dict:
    """One task's line of a pass: numbers and ids, never screen text."""
    summary = {}
    path = outcome.folder / "run.json"
    if path.is_file():
        summary = json.loads(path.read_text(encoding="utf-8"))
    calls = outcome.calls
    live = calls.get("live_seconds", 0.0)
    timing = summary.get("timing") or {}
    return {
        "pass": name,
        "task": outcome.task.id,
        "tier": outcome.task.tier,
        "tags": list(outcome.task.tags),
        "repeat": outcome.repeat,
        "score": outcome.score,
        "outcome": summary.get("outcome"),
        "said_done": summary.get("goal_achieved"),
        "error": outcome.error.split(":", 1)[0] if outcome.error else None,
        "steps": summary.get("steps_taken"),
        "oracle_steps": len(outcome.task.oracle),
        "seconds": outcome.seconds,
        "loop_seconds": round(outcome.seconds - live, 3),
        "model_seconds": round(calls.get("recorded_seconds", 0.0), 3),
        "timing": {k: v for k, v in (timing.get("mean") or {}).items() if k in PHASES},
        "calls": summary.get("usage_by_role") or {},
        "cost": summary.get("cost"),
        "spent": round(calls.get("spent", 0.0), 6),
        "sent": calls.get("sent", 0),
        "cached": calls.get("cached", 0),
        "handoffs": len(summary.get("handoffs") or []),
        "questions": len(summary.get("questions") or []),
        "models": sorted((summary.get("usage") or {}).keys()),
        "settings": settings,
        **git,
        "chromium": page.version,
        "machine": f"{platform.system()} {platform.machine()}",
    }


def run_pass(
    tasks: list[Task],
    *,
    where: Where,
    name: str | None = None,
    repeats: int = 1,
    headed: bool = False,
    ocr: str = "dom",
    latency: str = "typical",
    cached_only: bool = False,
    fresh: bool = False,
    say: Callable[[str], None] = print,
) -> tuple[Path, list[dict], str | None]:
    """Run every task `repeats` times with the real models, cached, and write one row per run.

    `fresh` asks again even where the shared cache holds a reply, and keeps what comes back in a cache
    of the pass's own. Returns the rows file, the rows, and why the pass stopped early, if it did."""
    name = name or stamp()
    cache = where.cache / "fresh" / name if fresh else where.cache
    settings_file = load_config(where)
    for role, variable in (("writer", "CLICKER_WRITER_MODEL"), ("answer", "CLICKER_ANSWER_MODEL")):
        if settings_file.get(role):
            os.environ[variable] = settings_file[role]
    where_decisions = decision_endpoint(settings_file, cached_only)
    inner_writer = writer_module.make_writer()
    ledger = CachedOnly() if cached_only else Ledger(where.ledger)
    settings = {"ocr": ocr, "latency": latency, "moves": config.moves_override(), "cached_only": cached_only, "fresh": fresh}
    git = git_state(where.root)
    out_file = where.passes / f"{name}.jsonl"
    rows: list[dict] = []
    stopped = None
    with MockPage(headed=headed) as page:
        for repeat in range(repeats):
            for task in tasks:
                folder = where.runs / name / f"{task.id.replace('/', '-')}-r{repeat}"
                clients: dict = {}

                def decisions(repeat=repeat, clients=clients) -> DecisionClient:
                    client = CachedDecisions(where_decisions, cache, repeat, ledger)
                    clients["decisions"] = client
                    return client

                cached_writer = CachedWriter(inner_writer, cache, repeat, ledger)
                outcome = run_task(
                    page, task, folder, decisions=decisions, writer=cached_writer, ocr=ocr, latency=latency, repeat=repeat
                )
                d = clients.get("decisions")
                outcome.calls = {
                    "sent": (d.sent if d else 0) + cached_writer.sent,
                    "cached": (d.cached if d else 0) + cached_writer.cached,
                    "spent": (d.spent if d else 0.0) + cached_writer.spent,
                    "live_seconds": (d.seconds if d else 0.0) + cached_writer.seconds,
                    "recorded_seconds": (d.recorded if d else 0.0) + cached_writer.recorded,
                }
                line = row(outcome, name, settings, page, git)
                rows.append(line)
                out_file.parent.mkdir(parents=True, exist_ok=True)
                with out_file.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(line, sort_keys=True) + "\n")
                write_replay(folder)
                say(describe(line))
                if outcome.error and outcome.error.startswith("budget"):
                    stopped = outcome.error
                    break
            if stopped:
                break
    write_index(where.runs / name, rows)
    return out_file, rows, stopped


def write_replay(folder: Path) -> None:
    from .replay import write

    if folder.is_dir():
        write(folder)


def write_index(folder: Path, rows: list[dict]) -> None:
    from .replay import index

    if folder.is_dir():
        index(folder, rows)


def describe(line: dict) -> str:
    """A row as one line for the terminal."""
    mark = "pass" if line["score"] else "FAIL"
    cost = f"${line['cost']:.4f}" if isinstance(line.get("cost"), int | float) else "$-"
    return (
        f"{mark}  {line['task']} r{line['repeat']}  {line['outcome']}  steps {line['steps']} (oracle {line['oracle_steps']})  "
        f"{line['seconds']:.1f}s  {cost} as if live, ${line['spent']:.4f} paid  sent {line['sent']} cached {line['cached']}"
        + (f"  [{line['error']}]" if line.get("error") else "")
    )

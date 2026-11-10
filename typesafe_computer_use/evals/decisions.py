"""Ask the decision model about the cases again, and score what it picks.

`decide.decide` runs as it does in a live step, on the case rebuilt with the current code, so a change
to how a request is built shows in the score. The client is the production one with a cache under its
`_post` and the budget in front of it: a request already asked, on the same repeat, costs nothing, so a
change that leaves a request alone leaves its answer alone and a pass only pays for what changed.
Repeats are separate samples, kept apart in the cache, because the model does not always pick the same
item twice and a change has to move a number by more than that to count.
"""

from __future__ import annotations

import hashlib
import json
import os
import statistics
import time
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path

from .. import decide
from ..calls import Calls, MeteredClassifier
from ..config import DEFAULT_MIN_CONFIDENCE, OPENROUTER_DECISIONS_URL
from ..decisions import DecisionClient, DecisionError, Endpoint, Refusal, is_settled
from .budget import BudgetError, Ledger
from .cases import Case, frozen_clock, rebuild, request
from .store import Home

DEFAULTS = {
    "decisions": "inception/mercury-decide",
    "writer": "inception/mercury-3",
    "answer": "openrouter/free",
    "floor": DEFAULT_MIN_CONFIDENCE,
}
Factory = Callable[[int], DecisionClient]
Selected = Sequence[tuple[Case, dict | None, str | None]]
ESTIMATE_USD = 0.002  # charged for a reply that reports no cost, so the cap still holds
FAILURE_STREAK = 5  # requests in a row that get no answer at all: the service is down, or the model is gone


def load_config(home: Home) -> dict:
    """The models a pass runs on, from `benchmarks/replay/config.json` over the defaults. Fixed in a
    file so that two passes are comparable, and every row records the model ids that answered."""
    path = home.replay / "config.json"
    given = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    return {**DEFAULTS, **given}


def endpoint_for(model: str) -> Endpoint:
    key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if not key:
        raise ValueError("a decision pass needs OPENROUTER_API_KEY (export it or put it in .env)")
    return Endpoint("openrouter", OPENROUTER_DECISIONS_URL, key, model)


def cache_key(body: dict, repeat: int) -> str:
    """What identifies a request in the cache: its body, and which sample of it this is."""
    return hashlib.sha256(json.dumps([body, repeat], sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def plan(selected: Selected, model: str, cache: Path, repeats: int, moves: bool | None = None) -> dict:
    """How many requests a pass would send and how many of those the cache already holds. Counts the
    first request of each decision; a refused question or an app question would add a few more."""
    cached = 0
    for repeat in range(repeats):
        for case, _, _ in selected:
            state, questions = request(case, moves)
            body = {"model": model, "state": state, "questions": {n: q.wire() for n, q in questions.items() if not is_settled(q)}}
            cached += (cache / f"{cache_key(body, repeat)}.json").is_file()
    asks = len(selected) * repeats
    return {"asks": asks, "cached": cached, "new": asks - cached}


class EvalClient(DecisionClient):
    """The decision client, with replies cached by request and every real request charged to the budget."""

    def __init__(self, where: Endpoint, cache: Path, repeat: int, ledger: Ledger | None = None, **kwargs) -> None:
        super().__init__(where, **kwargs)
        self.cache, self.repeat, self.ledger = cache, repeat, ledger
        self.sent = self.cached = 0
        self.seconds = self.spent = 0.0

    def _post(self, body: dict) -> dict:
        path = self.cache / f"{cache_key(body, self.repeat)}.json"
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                data = None
            if isinstance(data, dict):
                self.cached += 1
                return data
        if self.ledger is not None:
            self.ledger.require_funds()
        started = time.perf_counter()
        data = super()._post(body)
        self.seconds += time.perf_counter() - started
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        cost = usage.get("cost")
        cost = float(cost) if isinstance(cost, int | float) and not isinstance(cost, bool) else ESTIMATE_USD
        self.sent += 1
        self.spent += cost
        if self.ledger is not None:
            self.ledger.spend(cost, f"decision {body.get('model')}")
        self.cache.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
        return data


def pick_of(decision: decide.Decision, case: Case) -> dict:
    """A decision as the thing a label states: its kind, and the item it clicked or the site it opened."""
    kind = decision.kind.choice
    clicked = kind == "click_item" and decision.item is not None
    text = next((i["text"] for i in case.items if decision.item and str(i["index"]) == decision.item.choice), None)
    return {
        "kind": kind,
        **({"item": decision.item.choice, "item_text": text} if clicked else {}),
        **({"site": decision.site.choice} if kind == "use_browser" else {}),
        **({"shortcut": decision.shortcut.choice} if decision.shortcut is not None else {}),
        **({"target": decision.target.choice} if decision.target is not None else {}),
    }


def matches(expect: dict, pick: dict | None) -> bool:
    """Whether a pick is what a label says: the same kind, and the same item or site when it names one."""
    if pick is None or pick.get("kind") != expect.get("kind"):
        return False
    return all(pick.get(key) == expect[key] for key in ("item", "site") if key in expect)


def run_pass(
    selected: Selected, factory: Factory, repeats: int, moves: bool | None = None
) -> tuple[list[dict], dict, str | None]:
    """Ask every selected case `repeats` times. Returns a row per ask, how the clients were used, and
    why the pass stopped early (the budget, or FAILURE_STREAK requests in a row that got no answer), if it did.
    A refusal is the model's answer to a case, so it neither counts toward that streak nor ends it."""
    rows: list[dict] = []
    used = {"sent": 0, "cached": 0, "seconds": 0.0, "spent": 0.0, "models": set()}
    stopped = None
    failing = 0
    for repeat in range(repeats):
        with factory(repeat) as client:
            for case, want, source in selected:
                calls = Calls()
                row = {"id": case.id, "repeat": repeat, "source": source, "expect": want, "picked": None, "error": None}
                try:
                    r = rebuild(case)
                    with frozen_clock(case.state):
                        decision = decide.decide(
                            MeteredClassifier(client, calls),
                            r.goal,
                            r.screen,
                            r.items,
                            r.history,
                            r.browser,
                            r.email,
                            r.tried,
                            r.guidance,
                            r.browsers,
                            r.apps,
                            r.moves if moves is None else moves,
                        )
                except BudgetError as e:
                    stopped = str(e)
                    break
                except DecisionError as e:
                    row["error"] = str(e)[:200]
                    failing = 0 if isinstance(e, Refusal) else failing + 1
                    if failing >= FAILURE_STREAK:
                        stopped = f"{failing} requests in a row got no answer, so the pass stopped: {row['error']}"
                else:
                    failing = 0
                    row["picked"] = pick_of(decision, case)
                    row.update(
                        confidence=round(decision.confidence, 4),
                        kind_confidence=round(decision.kind.confidence, 4),
                        item_confidence=round(decision.item.confidence, 4) if decision.item else None,
                    )
                tokens = calls.tokens()
                row["input_tokens"] = sum(u["input_tokens"] for u in tokens.values())
                row["output_tokens"] = sum(u["output_tokens"] for u in tokens.values())
                row["cost"] = calls.cost()
                used["models"].update(tokens)
                row["correct"] = matches(want, row["picked"]) if want is not None else None
                rows.append(row)
                if stopped:
                    break
            used["sent"] += getattr(client, "sent", 0)
            used["cached"] += getattr(client, "cached", 0)
            used["seconds"] += getattr(client, "seconds", 0.0)
            used["spent"] += getattr(client, "spent", 0.0)
        if stopped:
            break
    used["models"] = sorted(used["models"])
    return rows, used, stopped


def summarize(rows: Sequence[dict], repeats: int, floor: float) -> dict:
    """The numbers a pass is judged by, for each kind of label and for the pass as a whole."""
    out: dict = {"asks": len(rows), "repeats": repeats, "floor": floor}
    by_case: dict[str, list[dict]] = {}
    for row in rows:
        by_case.setdefault(row["id"], []).append(row)
    for source in ("gold", "silver"):
        mine = [r for r in rows if r["source"] == source]
        cases = {r["id"] for r in mine}
        if not mine:
            continue
        sure = [r for r in mine if r.get("confidence") is not None]
        out[source] = {
            "cases": len(cases),
            "agree": round(sum(bool(r["correct"]) for r in mine) / len(mine), 4),
            "cases_mostly_right": sum(sum(bool(r["correct"]) for r in by_case[i]) * 2 > len(by_case[i]) for i in cases),
            "right_below_floor": sum(bool(r["correct"]) and r["confidence"] < floor for r in sure),
            "wrong_above_floor": sum(not r["correct"] and r["confidence"] >= floor for r in sure),
            "no_decision": sum(r["error"] is not None for r in mine),
        }
    if repeats > 1:
        picks = {i: {json.dumps(r["picked"], sort_keys=True) for r in rs} for i, rs in by_case.items() if len(rs) == repeats}
        out["same_pick_every_repeat"] = round(sum(len(p) == 1 for p in picks.values()) / len(picks), 4) if picks else None
    answered = [r for r in rows if r.get("input_tokens") is not None]
    if answered:
        out["input_tokens_per_ask"] = round(statistics.mean(r["input_tokens"] for r in answered))
        out["output_tokens_per_ask"] = round(statistics.mean(r["output_tokens"] for r in answered), 1)
        costs = [r["cost"] for r in answered if r["cost"] is not None]
        out["cost_per_ask"] = round(statistics.mean(costs), 6) if costs else None
    confidences = [r["confidence"] for r in rows if r.get("confidence") is not None]
    out["confidence_mean"] = round(statistics.mean(confidences), 4) if confidences else None
    out["kinds_picked"] = dict(Counter(r["picked"]["kind"] for r in rows if r["picked"]).most_common())
    return out


def misses(rows: Sequence[dict], limit: int = 15) -> list[dict]:
    """The wrong picks, the surest first: where the model and the label disagree most firmly."""
    wrong = [r for r in rows if r["correct"] is False]
    return sorted(wrong, key=lambda r: -(r.get("confidence") or 0.0))[:limit]

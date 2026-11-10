"""Where real runs failed, in a table small enough to read, and the stops worth labelling.

Read from the run folders themselves. It prints text from real screens, so it is for the terminal of the
machine that made them: nothing here is written anywhere that is committed.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from .store import Home

NOT_A_FAILURE = ("aborted", "dry run", "crashed")  # the user's own stop, a run that took no action, or no run at all
SHOW = 70  # characters of an item's text or a goal in the table


def outcome_of(summary: dict) -> str:
    """The outcome without the reason an abort gives: 'aborted (Ctrl-C)' is 'aborted'."""
    return str(summary.get("outcome") or "none").split(" (")[0]


def reviews(folder: Path) -> list[tuple[int, dict]]:
    """Every stop the answer model reviewed in a run: the step it came at, and the record."""
    found = []
    for path in sorted(folder.glob("step-*-review.json")):
        try:
            records = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        step = int(path.name.split("-")[1])
        found += [(step, r) for r in records if isinstance(r, dict)]
    return found


def decision_at(folder: Path, step: int) -> dict | None:
    """What the classifier answered on a step, or on the nearest step before it when it answered none
    (a run that stalls stops before it asks)."""
    for n in range(step, 0, -1):
        try:
            answers = json.loads((folder / f"step-{n:03d}-answers.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        by_index = {str(i["index"]): i["text"] for i in answers.get("items", [])}
        return {
            "id": f"{folder.name}/{n:03d}",
            "kind": answers.get("kind"),
            "kind_confidence": answers.get("kind_confidence"),
            "item_confidence": answers.get("item_confidence"),
            "item_text": by_index.get(str(answers.get("item"))),
            "app": answers.get("app"),
        }
    return None


def digest(home: Home, since: str | None = None) -> dict:
    """The runs of `runs/` that drove the machine, summarised. `since` is a run folder name, or the start of
    one such as `20261030-16`: runs before it are left out, because a failure from before a fix is no
    failure of the code as it is now."""
    outcomes: Counter = Counter()
    stops: Counter = Counter()
    sent_back: Counter = Counter()
    models: dict[str, dict] = defaultdict(
        lambda: {"runs": 0, "judged": 0, "achieved": 0, "actions": [], "seconds": [], "cost": []}
    )
    apps: Counter = Counter()
    apps_failed: Counter = Counter()
    candidates = []
    for folder in sorted(p for p in home.runs.glob("*") if p.is_dir() and (not since or p.name >= since)):
        try:
            summary = json.loads((folder / "run.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not summary.get("act") or (summary.get("config") or {}).get("image") not in (None, "None", ""):
            continue
        outcome = outcome_of(summary)
        achieved = summary.get("goal_achieved")
        outcomes[(outcome, achieved)] += 1
        model = (summary.get("models") or {}).get("decisions") or "unknown"
        m = models[model]
        m["runs"] += 1
        m["judged"] += achieved is not None
        m["achieved"] += achieved is True
        m["actions"].append(summary.get("steps_taken") or 0)
        m["seconds"].append(summary.get("seconds") or 0)
        if summary.get("cost") is not None:
            m["cost"].append(summary["cost"])
        found = reviews(folder)
        for _, record in found:
            stops[record.get("outcome")] += 1
            if record.get("handed_back"):
                sent_back[record.get("outcome")] += 1
        first = decision_at(folder, found[0][0]) if found else None
        for app, n in Counter(a for p in folder.glob("step-*-answers.json") if (a := _app(p)) is not None).items():
            apps[app] += n
            if achieved is not True:
                apps_failed[app] += n
        if found and achieved is not True and outcome not in NOT_A_FAILURE:
            candidates.append(
                {
                    "run": folder.name,
                    "stop_step": found[0][0],
                    "outcome": found[0][1].get("outcome"),
                    "goal": str(summary.get("goal") or "")[:SHOW],
                    "decision": first,
                }
            )
    return {
        "outcomes": {f"{o} / achieved={a}": n for (o, a), n in sorted(outcomes.items(), key=lambda kv: -kv[1])},
        "stops": dict(stops.most_common()),
        "sent_back": dict(sent_back.most_common()),
        "models": {
            name: {
                "runs": m["runs"],
                "judged": m["judged"],
                "achieved": m["achieved"],
                "actions_mean": round(statistics.mean(m["actions"]), 1),
                "seconds_mean": round(statistics.mean(m["seconds"]), 1),
                "cost_mean": round(statistics.mean(m["cost"]), 5) if m["cost"] else None,
            }
            for name, m in models.items()
        },
        "apps": {app: {"steps": n, "steps_in_runs_not_achieved": apps_failed[app]} for app, n in apps.most_common(8)},
        "candidates": candidates,
    }


def _app(answers_file: Path) -> str | None:
    try:
        return json.loads(answers_file.read_text(encoding="utf-8")).get("app")
    except (OSError, ValueError):
        return None


def render(result: dict, candidates: int = 25) -> str:
    lines = ["RUNS BY OUTCOME"]
    lines += [f"  {n:4d}  {name}" for name, n in result["outcomes"].items()]
    lines += ["", "STOPS THE ANSWER MODEL REVIEWED (and, apart, those it sent back to the classifier)"]
    lines += [f"  {n:4d}  {name}   (sent back {result['sent_back'].get(name, 0)})" for name, n in result["stops"].items()]
    lines += ["", "BY DECISION MODEL"]
    for name, m in result["models"].items():
        cost = f"${m['cost_mean']}" if m["cost_mean"] is not None else "-"
        lines.append(
            f"  {name}: {m['runs']} runs, {m['achieved']} of {m['judged']} judged achieved, "
            f"{m['actions_mean']} actions, {m['seconds_mean']} s, cost {cost}"
        )
    lines += ["", "BY APP (steps, and the steps in runs not judged achieved)"]
    lines += [f"  {app}: {a['steps']}, {a['steps_in_runs_not_achieved']}" for app, a in result["apps"].items()]
    lines += ["", f"FIRST STOP OF EACH RUN THAT FELL SHORT ({len(result['candidates'])}; showing the last {candidates})"]
    for c in result["candidates"][-candidates:]:
        d = c["decision"] or {}
        item = f" -> {d['item_text'][:SHOW]!r}" if d.get("item_text") else ""
        conf = lambda v: "-" if v is None else f"{v:.2f}"  # noqa: E731
        lines.append(
            f"  {d.get('id', c['run'])}  {c['outcome']}  {d.get('kind')} (kind {conf(d.get('kind_confidence'))}, "
            f"item {conf(d.get('item_confidence'))}){item}   goal: {c['goal']!r}"
        )
    return "\n".join(lines)

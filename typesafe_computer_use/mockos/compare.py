"""Read pass rows back: one pass as a table, or what changed between two.

Speed and cost are compared over the tasks solved in both passes, as `scripts/osworld results`
reports solved and failed tasks apart: a task that failed in one pass took a different path, and
its steps say nothing about the change. A number moved only when it moved by more than the spread
between repeats (docs/improvement-loop.md).
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path

from ..evals.store import read_jsonl

ROLES = ("decision", "reviewer", "writer")


def rows_of(name_or_path: str, passes: Path) -> list[dict]:
    """A pass's rows, by its name under `passes` or by the path of its rows file."""
    path = Path(name_or_path)
    if not path.is_file():
        path = passes / f"{name_or_path}.jsonl"
    if not path.is_file():
        raise FileNotFoundError(f"no pass named {name_or_path!r} (looked for {path})")
    return read_jsonl(path)


def requests(row: dict, role: str) -> int:
    return sum(int(u.get("requests") or 0) for u in (row.get("calls") or {}).get(role, {}).values())


def input_tokens(row: dict) -> int:
    return sum(int(u.get("input_tokens") or 0) for by_model in (row.get("calls") or {}).values() for u in by_model.values())


def settle(row: dict) -> float:
    return float((row.get("timing") or {}).get("settle") or 0.0)


def per_role(role: str):
    return lambda r: float(requests(r, role))


MEASURES = {
    "steps": lambda r: float(r.get("steps") or 0),
    **{f"{role} requests": per_role(role) for role in ROLES},
    "input tokens": lambda r: float(input_tokens(r)),
    "cost": lambda r: float(r.get("cost") or 0.0),
    "loop seconds": lambda r: float(r.get("loop_seconds") or 0.0),
    "settle seconds (mean per step)": settle,
    "model seconds": lambda r: float(r.get("model_seconds") or 0.0),
}


def by_task(rows: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        out[row["task"]].append(row)
    return out


def solved(runs: list[dict]) -> bool:
    """A task is solved in a pass when more than half its repeats passed the check."""
    return sum(int(r.get("score") or 0) for r in runs) * 2 > len(runs)


def spread(runs: list[dict], measure) -> float:
    values = [measure(r) for r in runs]
    return statistics.pstdev(values) if len(values) > 1 else 0.0


def compare(a: list[dict], b: list[dict]) -> str:
    lines: list[str] = []
    ta, tb = by_task(a), by_task(b)
    tasks = sorted(set(ta) | set(tb))
    both = [t for t in tasks if t in ta and t in tb and solved(ta[t]) and solved(tb[t])]
    lines.append(
        f"solved: {sum(solved(ta[t]) for t in ta)}/{len(ta)} in A, {sum(solved(tb[t]) for t in tb)}/{len(tb)} in B, {len(both)} in both"
    )
    for t in tasks:
        if t in ta and t in tb and solved(ta[t]) != solved(tb[t]):
            lines.append(f"  flipped: {t} {'solved -> failed' if solved(ta[t]) else 'failed -> solved'}")
        elif (t in ta) != (t in tb):
            lines.append(f"  only in {'A' if t in ta else 'B'}: {t}")
    for key in ("models", "chromium", "settings"):
        va = {json.dumps(r.get(key), sort_keys=True) for r in a}
        vb = {json.dumps(r.get(key), sort_keys=True) for r in b}
        if va != vb:
            lines.append(f"warning: the passes differ in {key}: {sorted(va)} vs {sorted(vb)}")
    if not both:
        lines.append("no task was solved in both passes, so there is nothing to compare speed and cost over")
        return "\n".join(lines)
    lines.append(f"over the {len(both)} tasks solved in both (mean per task, A -> B):")
    for name, measure in MEASURES.items():
        mean_a = statistics.mean(statistics.mean(measure(r) for r in ta[t]) for t in both)
        mean_b = statistics.mean(statistics.mean(measure(r) for r in tb[t]) for t in both)
        noise = max(statistics.mean(spread(ta[t], measure) for t in both), statistics.mean(spread(tb[t], measure) for t in both))
        moved = abs(mean_b - mean_a) > noise
        note = "" if moved or noise == 0 else f"  (within the spread between repeats, {noise:.3g})"
        lines.append(f"  {name:32s} {mean_a:10.4g} -> {mean_b:<10.4g}{note}")
        if moved:
            for t in both:
                da = statistics.mean(measure(r) for r in ta[t])
                db = statistics.mean(measure(r) for r in tb[t])
                if da != db:
                    lines.append(f"      {t}: {da:.4g} -> {db:.4g}")
    return "\n".join(lines)


def show(rows: list[dict]) -> str:
    lines = [
        f"{'':5s}{'task':34s}{'rep':>4s} {'outcome':16s}{'steps':>7s}{'secs':>8s}{'cost':>10s}{'paid':>10s}{'sent':>6s}{'cached':>8s}"
    ]
    for r in rows:
        cost = f"{r['cost']:.4f}" if isinstance(r.get("cost"), int | float) else "-"
        lines.append(
            f"{'pass' if r.get('score') else 'FAIL':5s}{r['task']:34s}{r.get('repeat', 0):>4d} {r.get('outcome')!s:16s}"
            f"{str(r.get('steps')) + '/' + str(r.get('oracle_steps')):>7s}{r.get('seconds', 0):>8.1f}{cost:>10s}"
            f"{r.get('spent', 0):>10.4f}{r.get('sent', 0):>6d}{r.get('cached', 0):>8d}"
        )
    scores = [int(r.get("score") or 0) for r in rows]
    if scores:
        lines.append(f"{sum(scores)}/{len(scores)} passed the check")
    return "\n".join(lines)

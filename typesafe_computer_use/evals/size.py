"""How many bytes a request is, by part, now and against a saved baseline.

The decision model bills every input token, so a request's size is a step's cost. This asks the current
code for the request of every case and measures it, with no model call.
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Sequence

from .cases import Case, request, sizes
from .store import Home, git_state, now_iso

PARTS = ("total", "state", "items_in_state", "q_kind", "q_item", "q_site", "q_browser", "q_offscreen")


def measure(cases: Sequence[Case], moves: bool = False) -> dict[str, dict[str, int]]:
    """Each case's request bytes by part, under the current code; `moves` for a run offered the moves
    beyond clicking and typing."""
    return {case.id: sizes(*request(case, moves)) for case in cases}


def aggregate(per_case: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
    out = {}
    for part in PARTS:
        values = sorted(s.get(part, 0) for s in per_case.values())
        if values and any(values):
            out[part] = {
                "mean": round(statistics.mean(values)),
                "median": round(statistics.median(values)),
                "p90": values[round(0.9 * (len(values) - 1))],
            }
    return out


def save_baseline(home: Home, per_case: dict[str, dict[str, int]]) -> None:
    home.baseline.parent.mkdir(parents=True, exist_ok=True)
    home.baseline.write_text(
        json.dumps({"at": now_iso(), **git_state(home.root), "per_case": per_case}, sort_keys=True), encoding="utf-8"
    )


def load_baseline(home: Home) -> dict | None:
    try:
        return json.loads(home.baseline.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def against(per_case: dict[str, dict[str, int]], baseline: dict[str, dict[str, int]]) -> dict[str, dict[str, float]]:
    """Each part's mean bytes now and before, over the cases both measured, and the change in percent."""
    shared = sorted(per_case.keys() & baseline.keys())
    out = {}
    for part in PARTS:
        now = statistics.mean(per_case[i].get(part, 0) for i in shared) if shared else 0
        before = statistics.mean(baseline[i].get(part, 0) for i in shared) if shared else 0
        if now or before:
            out[part] = {
                "now": round(now),
                "before": round(before),
                "change_pct": round(100 * (now - before) / before, 1) if before else 0.0,
                "cases": len(shared),
            }
    return out

"""What the loop sees of each app, in numbers: what a mock app is built to match.

`from_runs` reads the run folders a real run leaves (`runs/` by default; see docs/run-folder.md) and
counts, per app in front: the items each step was offered and where they came from, the roles of the
controls, the off-screen controls, and how long each step took to settle. It reads files and touches
nothing. Pointed at a pass's run folders under `.mockos/runs/`, it gives the mock's own numbers in
the same shape, for the two to be set side by side.

Only numbers and app names come out, never a label or a line of screen text.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def from_runs(root: Path) -> dict[str, dict]:
    """Numbers per app over every `step-NNN-answers.json` under `root`."""
    steps: dict[str, list[dict]] = defaultdict(list)
    for path in sorted(root.rglob("step-*-answers.json")):
        try:
            answers = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        steps[str(answers.get("app") or "?")].append(answers)
    return {app: numbers(found) for app, found in sorted(steps.items())}


def numbers(steps: list[dict]) -> dict:
    items = [len(s.get("items") or []) for s in steps]
    sources: Counter = Counter()
    roles: Counter = Counter()
    for s in steps:
        for it in s.get("items") or []:
            sources[it.get("source") or "ocr"] += 1
            if it.get("role"):
                roles[it["role"]] += 1
    total = sum(sources.values()) or 1
    offscreen = [len(s.get("offscreen_controls") or []) for s in steps]
    settles = [float((s.get("timing") or {}).get("settle")) for s in steps if (s.get("timing") or {}).get("settle") is not None]
    repeated = []
    for s in steps:
        texts = Counter(it.get("text") for it in s.get("items") or [])
        repeated.append(sum(n for n in texts.values() if n > 1))
    return {
        "steps": len(steps),
        "items": {"mean": round(statistics.mean(items), 1), "p50": percentile(items, 0.5), "p90": percentile(items, 0.9)},
        "source_share": {k: round(v / total, 3) for k, v in sorted(sources.items())},
        "roles_per_step": {k: round(v / len(steps), 2) for k, v in roles.most_common()},
        "repeated_texts_per_step": round(statistics.mean(repeated), 2),
        "offscreen_per_step": round(statistics.mean(offscreen), 1),
        "settle_seconds": {"p50": round(percentile(settles, 0.5), 3), "p90": round(percentile(settles, 0.9), 3)}
        if settles
        else None,
    }


def table(profiles: dict[str, dict]) -> str:
    if not profiles:
        return "no step files found"
    lines = [f"{'app':28s}{'steps':>6s}{'items p50':>11s}{'p90':>6s}{'ax share':>10s}{'offscreen':>11s}{'settle p50':>12s}"]
    for app, p in profiles.items():
        share = sum(v for k, v in p["source_share"].items() if k.startswith("ax"))
        settle = p["settle_seconds"]["p50"] if p["settle_seconds"] else 0.0
        lines.append(
            f"{app[:27]:28s}{p['steps']:>6d}{p['items']['p50']:>11.0f}{p['items']['p90']:>6.0f}{share:>10.2f}"
            f"{p['offscreen_per_step']:>11.1f}{settle:>12.2f}"
        )
    return "\n".join(lines)

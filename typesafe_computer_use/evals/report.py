"""The aggregate rows a pass leaves in `benchmarks/replay/`, and how a pass compares with the one before.

A row holds numbers and model ids, the commit it ran on, and whether the working copy differed from it.
It holds no goal, no screen text, and no case id, so it can be committed. Rows are never edited: a new
pass is a new row.
"""

from __future__ import annotations

import json
from pathlib import Path

from .store import Home, append_jsonl, git_state, now_iso, read_jsonl, stamp

SCHEMA = 1


def row(home: Home, kind: str, summary: dict, models: dict, batch: str | None) -> dict:
    return {"schema": SCHEMA, "kind": kind, "at": now_iso(), **git_state(home.root), "batch": batch, "models": models, **summary}


def record(home: Home, new: dict) -> Path:
    path = home.replay / f"{stamp()}.jsonl"
    append_jsonl(path, new)
    return path


def rows(home: Home, kind: str | None = None) -> list[dict]:
    """Every recorded row, oldest first."""
    found = []
    for path in sorted(home.replay.glob("*.jsonl")):
        found += [r for r in read_jsonl(path) if kind is None or r.get("kind") == kind]
    return found


def flatten(value: dict, prefix: str = "") -> dict[str, float]:
    """The numbers in a row, by dotted name."""
    out = {}
    for key, item in value.items():
        name = f"{prefix}{key}"
        if isinstance(item, dict):
            out.update(flatten(item, f"{name}."))
        elif isinstance(item, int | float) and not isinstance(item, bool):
            out[name] = item
    return out


def compare(before: dict, now: dict) -> list[str]:
    """Each number that changed between two rows of one kind, as a line."""
    a, b = flatten(before), flatten(now)
    lines = []
    for name in sorted(a.keys() & b.keys()):
        if name in ("schema",) or a[name] == b[name]:
            continue
        delta = b[name] - a[name]
        pct = f" ({100 * delta / a[name]:+.1f}%)" if a[name] else ""
        lines.append(f"  {name}: {a[name]} -> {b[name]}{pct}")
    return lines


def load_pass(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))

"""Where the eval kit keeps its files, and the git state a recorded row carries.

Everything built from a run folder holds text from a real screen, so it lives under `.private/evals/`
in the main checkout, which git ignores. Only aggregate rows, numbers and model ids, go to
`benchmarks/replay/`, which is committed.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

PRIVATE = Path(".private") / "evals"
REPLAY = Path("benchmarks") / "replay"


def checkout_root(start: Path | None = None) -> Path:
    """The main checkout, where `runs/` and `.private/` live, also when called from a worktree.

    A worktree's `.git` is a file naming `<main>/.git/worktrees/<name>`; the main checkout is three
    parents up. Read from the files themselves, so no git process is needed.
    """
    here = (start or Path.cwd()).resolve()
    for folder in (here, *here.parents):
        marker = folder / ".git"
        if marker.is_dir():
            return folder
        if marker.is_file():
            text = marker.read_text(encoding="utf-8").strip()
            if text.startswith("gitdir:"):
                gitdir = Path(text.removeprefix("gitdir:").strip())
                if gitdir.parent.name == "worktrees":
                    return gitdir.parent.parent.parent
            return folder
    return here


@dataclass(frozen=True)
class Home:
    """The folders the kit reads and writes, all under one checkout."""

    root: Path

    @property
    def runs(self) -> Path:
        return self.root / "runs"

    @property
    def private(self) -> Path:
        return self.root / PRIVATE

    @property
    def cases(self) -> Path:
        return self.private / "cases"

    @property
    def passes(self) -> Path:
        return self.private / "passes"

    @property
    def cache(self) -> Path:
        return self.private / "cache"

    @property
    def labels(self) -> Path:
        return self.private / "labels.jsonl"

    @property
    def ledger(self) -> Path:
        return self.private / "ledger.jsonl"

    @property
    def baseline(self) -> Path:
        return self.private / "baseline-size.json"

    @property
    def replay(self) -> Path:
        return self.root / REPLAY


def stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def read_jsonl(path: Path) -> list[dict]:
    """Every object in a JSON-lines file; a missing file is empty and a damaged line is skipped."""
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")


def git_state(root: Path) -> dict:
    """The commit a row was measured on, and whether the working copy differed from it."""

    def git(*args: str) -> str | None:
        try:
            done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            return None
        return done.stdout.strip() if done.returncode == 0 else None

    commit = git("rev-parse", "HEAD")
    status = git("status", "--porcelain", "--", ".", ":!.private", ":!runs", ":!benchmarks/replay")
    return {"git_commit": commit or "unknown", "git_dirty": bool(status)}

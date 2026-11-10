"""A dollar cap on the kit's model calls, kept in a ledger the user's approval opens.

Every command that asks a model checks the ledger first and refuses when no batch is open or the cap
is spent. The ledger is append-only JSON lines, so what was spent and why can be read back, and a
cap is the user's decision: only a `batch open` they approved starts one.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from .store import append_jsonl, now_iso, read_jsonl

RESERVE_USD = 0.01  # kept free before a call, since a call's cost is known only after it


class BudgetError(RuntimeError):
    """A command wanted to spend money it has no approved batch, or no money left in one, to spend."""


@dataclass(frozen=True)
class Batch:
    name: str
    cap_usd: float
    iterations: int
    spent_usd: float = 0.0
    iterations_used: int = 0

    @property
    def left_usd(self) -> float:
        return round(self.cap_usd - self.spent_usd, 6)

    def line(self) -> str:
        return (
            f"batch {self.name}: ${self.spent_usd:.4f} of ${self.cap_usd:.2f} spent, "
            f"iteration {self.iterations_used} of {self.iterations}"
        )


class Ledger:
    def __init__(self, path: Path) -> None:
        self.path = path

    def current(self) -> Batch | None:
        """The open batch, folded from the ledger's events: the latest `open` that no `close` followed."""
        batch: Batch | None = None
        for row in read_jsonl(self.path):
            event = row.get("event")
            if event == "open":
                batch = Batch(str(row["batch"]), float(row["cap_usd"]), int(row["iterations"]))
            elif event == "close":
                batch = None
            elif batch is not None and row.get("batch") == batch.name:
                if event == "spend":
                    batch = replace(batch, spent_usd=batch.spent_usd + float(row["usd"]))
                elif event == "iteration":
                    batch = replace(batch, iterations_used=batch.iterations_used + 1)
        return batch

    def open(self, cap_usd: float, iterations: int, name: str | None = None) -> Batch:
        if cap_usd <= 0 or iterations < 1:
            raise BudgetError("a batch needs a cap above zero and at least one iteration")
        if self.current() is not None:
            raise BudgetError(f"{self.current().line()} is still open; close it first")
        name = name or f"b{sum(1 for row in read_jsonl(self.path) if row.get('event') == 'open') + 1}"
        append_jsonl(self.path, {"at": now_iso(), "event": "open", "batch": name, "cap_usd": cap_usd, "iterations": iterations})
        return self.current()

    def close(self) -> Batch:
        batch = self.require()
        append_jsonl(self.path, {"at": now_iso(), "event": "close", "batch": batch.name})
        return batch

    def iteration(self, note: str = "") -> Batch:
        batch = self.require()
        if batch.iterations_used >= batch.iterations:
            raise BudgetError(f"{batch.line()}: no iteration is left in this batch")
        append_jsonl(self.path, {"at": now_iso(), "event": "iteration", "batch": batch.name, "note": note})
        return self.current()

    def require(self) -> Batch:
        batch = self.current()
        if batch is None:
            raise BudgetError(
                "no batch is open: the user approves a cap, then `clicker-eval batch open --cap USD --iterations N`"
            )
        return batch

    def require_funds(self) -> Batch:
        """The open batch, when it can pay for one more call."""
        batch = self.require()
        if batch.left_usd < RESERVE_USD:
            raise BudgetError(f"{batch.line()}: the cap is spent")
        return batch

    def spend(self, usd: float, what: str) -> Batch:
        batch = self.require()
        append_jsonl(self.path, {"at": now_iso(), "event": "spend", "batch": batch.name, "usd": round(usd, 6), "what": what})
        return self.current()

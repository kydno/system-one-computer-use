"""`clicker-mock`: the mock OS's tasks, oracle check, passes, and the readers of their rows.

`check`, `run` and `open` start a Chromium (headless unless `--headed`). On the maintainer's Mac
that needs their yes for each command, as any browser does (AGENTS.md). `run` asks the real models
for whatever its cache does not hold, inside the batch the user opened with `clicker-eval batch
open`; `run --cached-only` and every other command ask no model.

It is a command of its own and not one of `clicker-eval`'s: the eval kit never reaches the desktop
adapter (tests/test_import_boundaries.py), and a mock run drives one.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .. import config
from ..evals.budget import Ledger
from ..evals.store import stamp
from . import compare as compare_rows
from . import profile as profiles
from . import replay
from .page import LATENCIES

OCR_MODES = ("dom", "rapidocr", "vision")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="clicker-mock", description="Run the agent on the mock OS, a fake desktop in Chromium.")
    sub = parser.add_subparsers(dest="command", required=True)

    s = sub.add_parser("list", help="the tasks; no browser")
    s.add_argument("--tier", type=int)
    s.add_argument("--tag")

    s = sub.add_parser("check", help="run each task's scripted solution through the real loop: no model, no batch")
    s.add_argument("tasks", nargs="*", help="task ids (settings/toggle@1) or templates (settings/toggle); all when none")
    s.add_argument("--tier", type=int)
    s.add_argument("--tag")
    s.add_argument("--headed", action="store_true", help="show the Chromium window while it runs")
    s.add_argument("--ocr", choices=OCR_MODES, default="dom")
    s.add_argument("--latency", choices=LATENCIES, default="typical")

    s = sub.add_parser("run", help="a pass with the real models, cached, inside an open batch")
    s.add_argument("tasks", nargs="*")
    s.add_argument("--tier", type=int)
    s.add_argument("--tag")
    s.add_argument("--repeats", type=int, default=1, help="separate samples of each task, kept apart in the cache")
    s.add_argument("--headed", action="store_true")
    s.add_argument("--ocr", choices=OCR_MODES, default="dom")
    s.add_argument("--latency", choices=LATENCIES, default="typical")
    s.add_argument("--name", help="the pass's name (default: the time it started)")
    cache = s.add_mutually_exclusive_group()
    cache.add_argument("--cached-only", action="store_true", help="ask no model: every reply must be in the cache")
    cache.add_argument(
        "--no-cache",
        action="store_true",
        help="ask again even where the cache holds a reply: a new sample, kept apart from the shared cache",
    )

    s = sub.add_parser("compare", help="the differences between two passes; no browser")
    s.add_argument("a")
    s.add_argument("b")

    s = sub.add_parser("show", help="a pass's rows, or one run's; no browser")
    s.add_argument("name")
    s.add_argument("task", nargs="?")

    s = sub.add_parser("open", help="a task's starting state in a headed Chromium, to try by hand; prints the check")
    s.add_argument("task")

    s = sub.add_parser("replay", help="write replay.html for a run folder; no browser")
    s.add_argument("folder", type=Path)

    s = sub.add_parser("profile", help="what the loop sees of each app, in numbers; reads files only")
    p = s.add_subparsers(dest="profile", required=True)
    r = p.add_parser("runs", help="from the run folders in runs/ (or --from), per app in front")
    r.add_argument("--from", dest="source", type=Path, help="a folder of run folders (default: runs/ in the main checkout)")
    r.add_argument("--json", type=Path, help="also write the numbers to this file")

    args = parser.parse_args(argv)
    config.load_dotenv(Path.cwd() / ".env")
    try:
        sys.exit(COMMANDS[args.command](args) or 0)
    except (KeyError, FileNotFoundError, ValueError) as e:
        sys.exit(f"clicker-mock {args.command}: {e}")


def _list(args) -> int:
    from .tasks import select

    for task in select(tier=args.tier, tag=args.tag):
        print(f"{task.id:28s} tier {task.tier}  {','.join(task.tags):24s} {task.goal}")
    return 0


def _check(args) -> int:
    from .page import MockPage
    from .passes import Where, oracle
    from .tasks import select

    tasks = select(args.tasks, args.tier, args.tag)
    folder = Where.here().runs / f"check-{stamp()}"
    failed = 0
    with MockPage(headed=args.headed) as page:
        for task in tasks:
            outcome = oracle(page, task, folder / task.id.replace("/", "-"), ocr=args.ocr, latency=args.latency)
            replay.write(outcome.folder)
            steps = len(outcome.state.history) if outcome.state is not None else None
            exact = steps == task.best
            ok = outcome.score == 1 and exact
            failed += not ok
            why = "" if ok else f"  [{outcome.error or ('check failed' if not outcome.score else f'took {steps} steps')}]"
            ended = outcome.state.outcome if outcome.state is not None else "-"
            print(f"{'pass' if ok else 'FAIL'}  {task.id:28s} {ended:14s} steps {steps}/{task.best}  {outcome.seconds:.1f}s{why}")
    print(f"{len(tasks) - failed}/{len(tasks)} oracles passed; run folders: {folder}")
    return 1 if failed else 0


def _run(args) -> int:
    from .passes import Where, run_pass
    from .tasks import select

    where = Where.here()
    tasks = select(args.tasks, args.tier, args.tag)
    if not args.cached_only:
        batch = Ledger(where.ledger).current()
        print(batch.line() if batch else "no batch is open: only replies already in the cache can be used")
    path, rows, stopped = run_pass(
        tasks,
        where=where,
        name=args.name,
        repeats=args.repeats,
        headed=args.headed,
        ocr=args.ocr,
        latency=args.latency,
        cached_only=args.cached_only,
        fresh=args.no_cache,
    )
    print(compare_rows.show(rows))
    if stopped:
        print(f"the pass stopped early: {stopped}")
    print(f"rows: {path}\nreplays: {where.runs / path.stem / 'index.html'}")
    return 0


def _compare(args) -> int:
    from .passes import Where

    passes = Where.here().passes
    print(compare_rows.compare(compare_rows.rows_of(args.a, passes), compare_rows.rows_of(args.b, passes)))
    return 0


def _show(args) -> int:
    from .passes import Where

    where = Where.here()
    rows = compare_rows.rows_of(args.name, where.passes)
    if args.task is None:
        print(compare_rows.show(rows))
        return 0
    picked = [r for r in rows if r["task"] == args.task]
    if not picked:
        raise KeyError(f"pass {args.name!r} has no task {args.task!r}")
    for r in picked:
        print(json.dumps(r, indent=2))
        folder = where.runs / Path(args.name).stem / f"{r['task'].replace('/', '-')}-r{r['repeat']}"
        print(f"run folder: {folder}\nreplay: {folder / 'replay.html'}")
    return 0


def _open(args) -> int:
    from .page import MockPage
    from .tasks import select

    task = select([args.task])[0]
    with MockPage(headed=True) as page:
        page.load(task.seed)
        print(f"{task.id}: {task.goal}\nThe mock OS is open. Press Enter to check its state, Ctrl-D to close.")
        while True:
            try:
                input()
            except (EOFError, KeyboardInterrupt):
                break
            print(
                "check: " + ("pass" if task.check(page.dump(), None) else "fail") + " (a question's answer is not checked here)"
            )
    return 0


def _replay(args) -> int:
    print(replay.write(args.folder))
    return 0


def _profile(args) -> int:
    from ..evals.store import checkout_root

    source = args.source or checkout_root() / "runs"
    numbers = profiles.from_runs(source)
    print(profiles.table(numbers))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(numbers, indent=2), encoding="utf-8")
        print(f"written: {args.json}")
    return 0


COMMANDS = {
    "list": _list,
    "check": _check,
    "run": _run,
    "compare": _compare,
    "show": _show,
    "open": _open,
    "replay": _replay,
    "profile": _profile,
}

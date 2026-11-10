"""`clicker-eval`: the offline eval kit. None of its commands drives this machine; the ones that ask a
model run only inside a batch the user approved (see budget.py and docs/improvement-loop.md)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .. import config
from . import budget, cases, decisions, digest, report, size
from .store import Home, append_jsonl, checkout_root, now_iso, stamp

SHOW_ITEMS = 40


def home_of(args: argparse.Namespace) -> Home:
    return Home(Path(args.home).resolve() if args.home else checkout_root())


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="clicker-eval", description=__doc__)
    p.add_argument("--home", help="the checkout holding runs/ and .private/ (default: the main checkout of this one)")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("harvest", help="freeze every saved step into a case under .private/evals/cases")
    s.add_argument("--force", action="store_true", help="freeze runs again that are already frozen")

    sub.add_parser("check", help="how many cases the current code rebuilds exactly as they were sent")

    s = sub.add_parser("digest", help="where real runs failed, and the stops worth labelling")
    s.add_argument("--candidates", type=int, default=25)
    s.add_argument("--since", help="only runs from this folder name on, such as 20261030-16: the last change to the loop")

    s = sub.add_parser("show", help="one case, compactly, to decide what it should have done")
    s.add_argument("id", help="<run folder>/<step>, as the digest prints it")
    s.add_argument("--items", type=int, default=SHOW_ITEMS, help="how many items to list")
    s.add_argument("--grep", help="list only the items whose text holds this")

    s = sub.add_parser("label", help="record the right action for a case (a gold label)")
    s.add_argument("id")
    s.add_argument("--kind", required=True, help="the action kind that was right, such as click_item or scroll_down")
    s.add_argument("--item", help="the index of the item to click (see `show`)")
    s.add_argument("--text", help="the text of the item to click, when only one item reads so")
    s.add_argument("--site", help="the site key for use_browser")
    s.add_argument("--note", default="")

    sub.add_parser("labels", help="list the gold labels")

    s = sub.add_parser("size", help="request bytes by part under the current code; no model call")
    s.add_argument("--save-baseline", action="store_true", help="keep this measurement as the baseline later ones compare with")
    s.add_argument("--runs", nargs="*", help="only these run folders")
    s.add_argument(
        "--moves",
        action="store_const",
        const=True,
        default=None,
        help="offer the moves beyond clicking and typing in every case; by default each case is asked as its own run was",
    )

    s = sub.add_parser("decisions", help="ask the decision model about the labelled cases and score its picks")
    s.add_argument("--only", choices=("gold", "silver", "labeled", "all"), default="labeled")
    s.add_argument("--repeats", type=int, default=1)
    s.add_argument("--limit", type=int, help="the first N cases of the selection")
    s.add_argument("--runs", nargs="*", help="only these run folders")
    s.add_argument("--plan", action="store_true", help="count the requests a pass would send, and how many are already cached")
    s.add_argument("--misses", type=int, default=10, help="how many wrong picks to list")
    s.add_argument(
        "--moves",
        action="store_const",
        const=True,
        default=None,
        help="offer the moves beyond clicking and typing in every case; by default each case is asked as its own run was",
    )

    s = sub.add_parser("batch", help="open, inspect, advance, or close the budget the user approved")
    s.add_argument("action", choices=("open", "status", "iteration", "close"))
    s.add_argument("--cap", type=float, help="dollars the batch may spend (open)")
    s.add_argument("--iterations", type=int, help="iterations the batch may run (open)")
    s.add_argument("--name")
    s.add_argument("--note", default="")

    s = sub.add_parser("report", help="the recorded rows, or record a pass as a new row in benchmarks/replay")
    s.add_argument("--record", type=Path, help="a pass file from .private/evals/passes to append as a row")
    s.add_argument("--kind", help="only this kind of row (size, decisions)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    home = home_of(args)
    try:
        return COMMANDS[args.command](home, args) or 0
    except (budget.BudgetError, ValueError) as e:
        print(f"clicker-eval: {e}", file=sys.stderr)
        return 2


# ------------------------------------------------------------------ commands


def do_harvest(home: Home, args: argparse.Namespace) -> None:
    stats = cases.harvest(home, args.force)
    print(f"{stats['runs']} runs frozen, {stats['cases']} cases ({stats['new_cases']} new) in {home.cases}")


def do_check(home: Home, args: argparse.Namespace) -> None:
    every = cases.load_cases(home)
    differs: dict[str, int] = {}
    exact = 0
    for case in every:
        found = cases.fidelity(case)
        exact += not found
        for part in found:
            differs[part] = differs.get(part, 0) + 1
    print(f"{exact} of {len(every)} cases rebuild exactly as they were sent")
    if differs:
        print(f"the rest differ in: {differs} (wording that changed in decide.py since the run, or a rebuild that is wrong)")


def do_digest(home: Home, args: argparse.Namespace) -> None:
    print(digest.render(digest.digest(home, args.since), args.candidates))


def find_case(home: Home, case_id: str) -> cases.Case:
    run = case_id.split("/")[0]
    for case in cases.load_cases(home, [run]):
        if case.id == case_id:
            return case
    raise ValueError(f"no case {case_id!r}: run `clicker-eval harvest`, and name it <run folder>/<step>")


def do_show(home: Home, args: argparse.Namespace) -> None:
    case = find_case(home, args.id)
    print(f"{case.id}  run {case.run_outcome} (judged achieved: {case.achieved})  decisions {case.models.get('decisions')}")
    print(f"goal: {case.goal}")
    print(f"app: {case.app}  url: {case.url}")
    if case.field:
        print(f"field: {case.field.get('role')} {case.field.get('label')!r} value {str(case.field.get('value'))[:60]!r}")
    state = case.state
    for key in ("current_focus", "user_said", "previous_actions", "already_tried_on_this_screen"):
        if state.get(key):
            print(f"{key}: {json.dumps(state[key], ensure_ascii=False)[:600]}")
    p = case.picked
    print(
        f"picked: {p['kind']} (kind {p['kind_confidence']:.2f}"
        + (f", item {p['item_confidence']:.2f}" if p.get("item_confidence") is not None else "")
        + f") item {p.get('item')} {str(p.get('item_text'))[:80]!r}"
    )
    stops = digest.reviews(home.runs / case.run)
    for step, record in stops:
        if step == case.step:
            said = {
                k: record.get(k)
                for k in ("outcome", "achieved", "answer", "focus", "question", "wait", "scroll")
                if record.get(k)
            }
            print(f"answer model at this stop: {json.dumps(said, ensure_ascii=False)[:700]}")
    listed = [i for i in case.items if not args.grep or args.grep.casefold() in str(i["text"]).casefold()]
    print(f"items ({len(case.items)}; showing {min(len(listed), args.items)}, picked marked >>):")
    for i in listed[: args.items]:
        mark = ">>" if str(i["index"]) == str(p.get("item")) else "  "
        role = f"{i['role']} " if i.get("role") else ""
        print(f" {mark}[{i['index']:3d}] {role}{str(i['text'])[:90]!r}")
    print(f"raw capture: {home.runs / case.run / f'step-{case.step:03d}.png'} (annotated)")


def do_label(home: Home, args: argparse.Namespace) -> None:
    case = find_case(home, args.id)
    allowed = {*case.criteria["kind"], "press_offscreen"}
    if args.kind not in allowed:
        raise ValueError(f"{args.kind!r} was not offered at this step; it offered {sorted(allowed)}")
    expect: dict = {"kind": args.kind}
    if args.kind == "click_item":
        if args.item is not None:
            hit = next((i for i in case.items if str(i["index"]) == str(args.item)), None)
        else:
            if not args.text:
                raise ValueError("click_item needs --item INDEX or --text TEXT")
            found = [i for i in case.items if i["text"] == args.text]
            if len(found) != 1:
                raise ValueError(f"{len(found)} items read {args.text!r}: name the one by --item INDEX (see `show`)")
            hit = found[0]
        if hit is None:
            raise ValueError(f"no item {args.item} in this case")
        expect.update(item=str(hit["index"]), item_text=hit["text"])
    if args.kind == "use_browser":
        if args.site is None or args.site not in case.criteria.get("site", {}):
            raise ValueError(f"use_browser needs --site, one of {sorted(case.criteria.get('site', {}))}")
        expect["site"] = args.site
    append_jsonl(home.labels, {"id": case.id, "expect": expect, "source": "gold", "note": args.note, "at": now_iso()})
    print(f"labelled {case.id}: {json.dumps(expect, ensure_ascii=False)}")


def do_labels(home: Home, args: argparse.Namespace) -> None:
    labels = cases.load_labels(home)
    for case_id, expect in sorted(labels.items()):
        print(f"{case_id}  {json.dumps(expect, ensure_ascii=False)}")
    print(f"{len(labels)} gold labels")


def chosen_cases(home: Home, runs: list[str] | None) -> list[cases.Case]:
    every = cases.load_cases(home, runs)
    if not every:
        raise ValueError("no cases: run `clicker-eval harvest` first")
    return every


def do_size(home: Home, args: argparse.Namespace) -> None:
    every = chosen_cases(home, args.runs)
    per_case = size.measure(every, args.moves)
    parts = size.aggregate(per_case)
    print(f"request bytes under the current code{', with the moves offered' if args.moves else ''}, over {len(every)} cases")
    for part, v in parts.items():
        print(f"  {part:15s} mean {v['mean']:6d}  median {v['median']:6d}  p90 {v['p90']:6d}")
    base = size.load_baseline(home)
    summary: dict = {"cases": len(every), "bytes": parts}
    if base:
        delta = size.against(per_case, base["per_case"])
        summary["against_baseline"] = delta
        print(f"against the baseline of {base.get('at')} (commit {str(base.get('git_commit'))[:8]}):")
        for part, d in delta.items():
            print(f"  {part:15s} {d['before']:6d} -> {d['now']:6d}  {d['change_pct']:+.1f}%")
    if args.save_baseline:
        size.save_baseline(home, per_case)
        print(f"saved as the baseline: {home.baseline}")
    write_pass(home, "size", summary, {})


def write_pass(home: Home, kind: str, summary: dict, models: dict, rows: list[dict] | None = None) -> Path:
    home.passes.mkdir(parents=True, exist_ok=True)
    path = home.passes / f"{stamp()}-{kind}.json"
    path.write_text(
        json.dumps({"kind": kind, "summary": summary, "models": models, "rows": rows or []}, sort_keys=True), encoding="utf-8"
    )
    return path


def do_decisions(home: Home, args: argparse.Namespace) -> None:
    config.load_dotenv(home.root / ".env")
    settings = decisions.load_config(home)
    labels = cases.load_labels(home)
    selected = cases.select(chosen_cases(home, args.runs), labels, args.only)
    if args.limit:
        selected = selected[: args.limit]
    if not selected:
        raise ValueError("no case has a label: `clicker-eval label`, or take a run the answer model judged achieved")
    gold = sum(source == "gold" for _, _, source in selected)
    print(
        f"{len(selected)} cases ({gold} gold, {len(selected) - gold} silver) x {args.repeats} repeats on {settings['decisions']}"
    )
    ledger = budget.Ledger(home.ledger)
    if args.plan:
        plan = decisions.plan(selected, settings["decisions"], home.cache, args.repeats, args.moves)
        print(
            f"{plan['asks']} requests, {plan['cached']} already cached, {plan['new']} new: "
            f"at most ${plan['new'] * decisions.ESTIMATE_USD:.3f} against {ledger.current().line() if ledger.current() else 'no open batch'}"
        )
        return
    ledger.require_funds()
    where = decisions.endpoint_for(settings["decisions"])
    rows, used, stopped = decisions.run_pass(
        selected, lambda repeat: decisions.EvalClient(where, home.cache, repeat, ledger), args.repeats, args.moves
    )
    if rows and all(r["error"] for r in rows):
        raise ValueError(
            f"nothing was answered, so no pass was saved ({len(rows)} asks failed; {ledger.current().line()}): {stopped or rows[0]['error']}"
        )
    summary = decisions.summarize(rows, args.repeats, float(settings["floor"]))
    summary.update(
        requests_sent=used["sent"], requests_cached=used["cached"], cost_spent=round(used["spent"], 6), moves=args.moves is True
    )
    summary["stopped_early"] = stopped
    models = {"configured": settings["decisions"], "named_by_replies": used["models"]}
    path = write_pass(home, "decisions", summary, models, rows)
    print(json.dumps(summary, indent=2, sort_keys=True))
    for row in decisions.misses(rows, args.misses):
        print(
            f"  miss {row['id']} r{row['repeat']} [{row['source']}] expected {row['expect']} got {row['picked']} ({row.get('confidence')})"
        )
    print(f"{ledger.current().line()}\npass saved: {path}")
    if stopped:
        print(f"STOPPED EARLY: {stopped}", file=sys.stderr)


def do_batch(home: Home, args: argparse.Namespace) -> None:
    ledger = budget.Ledger(home.ledger)
    if args.action == "open":
        if args.cap is None or args.iterations is None:
            raise ValueError("batch open needs --cap USD and --iterations N, as the user approved them")
        print(ledger.open(args.cap, args.iterations, args.name).line())
    elif args.action == "status":
        batch = ledger.current()
        print(batch.line() if batch else "no batch is open")
    elif args.action == "iteration":
        print(ledger.iteration(args.note).line())
    else:
        print("closed " + ledger.close().line())


def do_report(home: Home, args: argparse.Namespace) -> None:
    if args.record:
        saved = report.load_pass(args.record)
        batch = budget.Ledger(home.ledger).current()
        new = report.row(home, saved["kind"], saved["summary"], saved.get("models") or {}, batch.name if batch else None)
        before = report.rows(home, saved["kind"])
        path = report.record(home, new)
        print(f"recorded in {path}")
        if before:
            print("against the row before:")
            print("\n".join(report.compare(before[-1], new)) or "  no number changed")
        return
    found = report.rows(home, args.kind)
    for r in found[-10:]:
        print(
            f"{r['at']}  {r['kind']}  commit {str(r.get('git_commit'))[:8]}{' (dirty)' if r.get('git_dirty') else ''}  batch {r.get('batch')}"
        )
    if len(found) >= 2 and found[-1]["kind"] == found[-2]["kind"]:
        print("last two of a kind:")
        print("\n".join(report.compare(found[-2], found[-1])) or "  no number changed")


COMMANDS = {
    "harvest": do_harvest,
    "check": do_check,
    "digest": do_digest,
    "show": do_show,
    "label": do_label,
    "labels": do_labels,
    "size": do_size,
    "decisions": do_decisions,
    "batch": do_batch,
    "report": do_report,
}

if __name__ == "__main__":
    raise SystemExit(main())

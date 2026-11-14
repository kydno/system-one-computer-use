"""A saved step, frozen as a case, and rebuilt into the request a live step would send.

A run folder keeps, per step, the exact state and criteria that went to the decision model
(`step-NNN-payload.txt`) and the structured items and the pick (`step-NNN-answers.json`). A case holds
both. `rebuild` turns the items back into the objects the loop used and asks the loop's own functions
(`decide.base_state`, `decide.build_questions`) for the request, with the clock held at the step's own
time, so a change to `decide.py` shows up as a change in the request, and `fidelity` says which cases
the current code no longer reproduces as they were sent.

A case holds text from a real screen. It lives in `.private/evals/` and is never committed.
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import date
from functools import partial
from pathlib import Path
from unittest import mock

from PIL import Image

from .. import decide
from ..dates import date_hints
from ..decisions import Choice, is_settled
from ..models import ROLE_WORDS, AxNode, Exchange, Field, Guidance, Item, Popup, Screen
from .store import Home, read_jsonl

RULE = "=" * 78
CAPTURE = re.compile(r"pixel boxes on the (\d+)x(\d+) capture, scale ([\d.]+)")
STEP_FILE = re.compile(r"step-(\d+)-answers\.json$")
WORD_ROLES = {word: role for role, word in ROLE_WORDS.items()}
QUESTIONS = ("kind", "item", "site", "browser", "offscreen")  # the criteria a payload file prints, by question
PLACEHOLDER_EMAIL = "user@example.com"  # the email's value never reaches a request; only whether one is set does


@dataclass
class Case:
    """One decision the loop made, with everything it was shown."""

    id: str  # "<run folder>/<step>"
    run: str
    step: int
    goal: str
    acted: bool  # the run drove the machine, so its picks were carried out
    run_outcome: str | None
    achieved: bool | None  # the answer model's verdict on the run
    models: dict
    capture: list[int]  # width and height of the capture, in pixels
    scale: float
    app: str
    url: str | None
    field: dict | None
    state: dict  # as sent
    criteria: dict[str, dict]  # each question's criteria, as sent
    app_criteria: dict | None
    items: list[dict]
    offscreen: list[dict]
    picked: dict

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict) -> Case:
        return cls(**data)


# ------------------------------------------------------------------ reading a run folder


def sections(text: str) -> dict[str, str]:
    """A payload file's sections, by the first line of their heading."""
    parts = text.split(RULE + "\n")
    return {head.strip().splitlines()[0]: body for head, body in zip(parts[1::2], parts[2::2], strict=False)}


def _section(found: dict[str, str], prefix: str) -> str | None:
    return next((body for head, body in found.items() if head == prefix or head.startswith(prefix + "  ")), None)


def _json(body: str | None):
    if body is None:
        return None
    try:
        return json.JSONDecoder().raw_decode(body.lstrip())[0]
    except ValueError:
        return None


def harvest_step(run: str, step: int, summary: dict, answers_file: Path, payload_file: Path) -> Case | None:
    """One saved step as a case, or None when its files do not hold what a case needs."""
    try:
        answers = json.loads(answers_file.read_text(encoding="utf-8"))
        found = sections(payload_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    state = _json(_section(found, "STATE"))
    heading = next((head for head in found if head.startswith("ITEMS")), "")
    capture = CAPTURE.search(heading)
    criteria = {name: c for name in QUESTIONS if isinstance(c := _json(_section(found, f"QUESTION {name}")), dict)}
    if not isinstance(state, dict) or capture is None or "kind" not in criteria or not isinstance(answers.get("items"), list):
        return None
    items = answers["items"]
    app_criteria = _json(_section(found, "QUESTION app"))
    by_index = {str(item["index"]): item for item in items}
    chosen = answers.get("item")
    config = summary.get("config") or {}
    return Case(
        id=f"{run}/{step:03d}",
        run=run,
        step=step,
        goal=str(summary.get("goal") or state.get("goal") or ""),
        acted=bool(summary.get("act")) and config.get("image") in (None, "None", ""),
        run_outcome=summary.get("outcome"),
        achieved=summary.get("goal_achieved"),
        models=summary.get("models") or {},
        capture=[int(capture[1]), int(capture[2])],
        scale=float(capture[3]),
        app=str(answers.get("app") or state.get("frontmost_app") or ""),
        url=answers.get("url"),
        field=answers.get("field"),
        state=state,
        criteria=criteria,
        app_criteria=app_criteria if isinstance(app_criteria, dict) else None,
        items=items,
        offscreen=answers.get("offscreen_controls") or [],
        picked={
            "kind": answers.get("kind"),
            "item": chosen,
            "item_text": by_index[chosen]["text"] if chosen in by_index else None,
            "site": answers.get("site"),
            "kind_confidence": answers.get("kind_confidence"),
            "item_confidence": answers.get("item_confidence"),
            "confidence": answers.get("confidence"),
            "chosen": answers.get("chosen"),
        },
    )


def harvest_run(folder: Path) -> list[Case]:
    try:
        summary = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    cases = []
    for answers_file in sorted(folder.glob("step-*-answers.json")):
        number = STEP_FILE.search(answers_file.name)
        if number is None:
            continue
        case = harvest_step(folder.name, int(number[1]), summary, answers_file, folder / f"step-{number[1]}-payload.txt")
        if case is not None:
            cases.append(case)
    return cases


def harvest(home: Home, force: bool = False) -> dict:
    """Freeze every run folder under `runs/` into `.private/evals/cases/<run>.jsonl`. A run already
    frozen is left alone unless `force`: a folder does not change once its run has ended."""
    home.cases.mkdir(parents=True, exist_ok=True)
    runs = new = cases = 0
    for folder in sorted(p for p in home.runs.glob("*") if p.is_dir()):
        target = home.cases / f"{folder.name}.jsonl"
        if target.exists() and not force:
            runs += 1
            cases += len(read_jsonl(target))
            continue
        found = harvest_run(folder)
        if not found:
            continue
        target.write_text("".join(json.dumps(c.to_json(), sort_keys=True) + "\n" for c in found), encoding="utf-8")
        runs += 1
        new += len(found)
        cases += len(found)
    return {"runs": runs, "cases": cases, "new_cases": new}


def load_cases(home: Home, runs: Sequence[str] | None = None) -> list[Case]:
    wanted = set(runs) if runs else None
    out = []
    for path in sorted(home.cases.glob("*.jsonl")):
        if wanted is None or path.stem in wanted:
            out += [Case.from_json(row) for row in read_jsonl(path)]
    return out


# ------------------------------------------------------------------ labels


def expectation(picked: dict) -> dict:
    """What a pick stands for when it is taken as the right one: its kind, and for a click the item
    (its index, which is fixed in a frozen case, and its text) or for a browser the site."""
    kind = picked.get("kind")
    clicked = kind in ("click_item", *decide.POINTING) and picked.get("item") is not None
    return {
        "kind": kind,
        **({"item": str(picked["item"]), "item_text": picked.get("item_text")} if clicked else {}),
        **({"site": picked["site"]} if kind == "use_browser" and picked.get("site") else {}),
    }


def load_labels(home: Home) -> dict[str, dict]:
    """The gold labels, by case id; a later label for a case replaces an earlier one."""
    return {row["id"]: row["expect"] for row in read_jsonl(home.labels) if "id" in row and isinstance(row.get("expect"), dict)}


def expected(case: Case, labels: dict[str, dict]) -> tuple[dict, str] | None:
    """What a case should decide, and how sure we are of it: a gold label someone set, else the pick
    of a run the answer model judged successful (silver), else nothing."""
    if case.id in labels:
        return labels[case.id], "gold"
    if case.acted and case.achieved is True and case.picked.get("kind"):
        return expectation(case.picked), "silver"
    return None


def select(cases: Sequence[Case], labels: dict[str, dict], only: str = "labeled") -> list[tuple[Case, dict | None, str | None]]:
    """The cases a pass runs, each with what it should decide. `only` is gold, silver, labeled, or all."""
    chosen = []
    for case in cases:
        want = expected(case, labels)
        source = want[1] if want else None
        if only == "all" or (only == "labeled" and source) or only == source:
            chosen.append((case, want[0] if want else None, source))
    return chosen


# ------------------------------------------------------------------ rebuilding the request


@dataclass
class Rebuilt:
    screen: Screen
    items: list[Item]
    goal: str
    history: list[str]
    tried: list[str]
    guidance: Guidance
    browser: str
    browsers: tuple[str, ...]
    email: str | None
    apps: tuple[str, ...]
    moves: bool = False  # the run was offered the moves beyond clicking and typing


def _popup(under: str) -> Popup:
    """The popup a line says an item is under: its quoted name, or 'a popup' when it has none."""
    try:
        name = ast.literal_eval(under)
    except (ValueError, SyntaxError):
        name = ""
    return Popup(str(name) if isinstance(name, str) else "", 0.0, 0.0, 0.0, 0.0)


def _environment(case: Case) -> tuple[str, tuple[str, ...], tuple[str, ...], str | None, bool]:
    """The browser, the other browsers, the apps, the email, and whether the run was offered the moves
    beyond clicking and typing, read back from the criteria the step sent."""
    kind = case.criteria["kind"]
    which = case.criteria.get("browser")
    if which:
        names = list(which)
        browser = next((name for name, text in which.items() if "the default" in str(text)), names[0])
        browsers = tuple(name for name in names if name != browser)
    else:
        found = re.match(r"Work in (.+?): bring it to the front", str(kind.get("use_browser", "")))
        browser, browsers = (found[1] if found else "Google Chrome"), ()
    apps = tuple(name for name in (case.app_criteria or {}) if name != "none") or (
        ("(unknown app)",) if "open_app" in kind else ()
    )
    return browser, browsers, apps, PLACEHOLDER_EMAIL if "type_email" in kind else None, bool(decide.GATED_KINDS & set(kind))


def rebuild(case: Case) -> Rebuilt:
    items = [Item(**item) for item in case.items]
    state = case.state
    covered = {i["i"]: _popup(i["under"]) for i in state.get("screen_items_in_reading_order", []) if i.get("under")}
    clicked_before = {
        i["i"]: i["clicked_before"] for i in state.get("screen_items_in_reading_order", []) if i.get("clicked_before")
    }
    screen = Screen(
        image=Image.new("1", (case.capture[0], case.capture[1])),  # only its size is read
        scale=case.scale,
        app=case.app,
        field=Field(**case.field) if case.field else None,
        url=case.url,
        offscreen=[
            AxNode(role=WORD_ROLES.get(o["role"], "AXUnknown"), label=o["label"], x=0.0, y=0.0, w=0.0, h=0.0, pressable=True)
            for o in case.offscreen
        ],
        covered=covered,
        clicked_before=clicked_before,
    )
    guidance = Guidance(
        focus=state.get("current_focus"),
        plan=state.get("plan"),
        exchanges=tuple(Exchange(e["asked"], e["replied"]) for e in state.get("user_said", [])),
    )
    browser, browsers, apps, email, moves = _environment(case)
    return Rebuilt(
        screen=screen,
        items=items,
        goal=case.goal,
        history=list(state.get("previous_actions", [])),
        tried=list(state.get("already_tried_on_this_screen", [])),
        guidance=guidance,
        browser=browser,
        browsers=browsers,
        email=email,
        apps=apps,
        moves=moves,
    )


@contextmanager
def frozen_clock(state: dict) -> Iterator[None]:
    """Hold the clock the request reads at the time the step ran: what 'in 27 days' counts from, and
    the time in the state. Without it a case rebuilt next week would be a different request."""
    now = state.get("now") or {}
    today = date.fromisoformat(now["today"]) if now.get("today") else None
    with (
        mock.patch.object(decide, "now_context", lambda: now),
        mock.patch.object(decide, "date_hints", partial(date_hints, today=today)),
    ):
        yield


def request(case: Case, moves: bool | None = None) -> tuple[dict, dict[str, Choice]]:
    """The state and questions the current code would send for this case. The run is offered the moves
    beyond clicking and typing when its own step was (the kinds are in the criteria it sent); `moves`
    forces that on or off for the case."""
    r = rebuild(case)
    moves = r.moves if moves is None else moves
    with frozen_clock(case.state):
        state = decide.base_state(r.goal, r.screen, r.items, r.history, r.tried, r.guidance, moves)
        questions = decide.build_questions(r.screen, r.items, r.browser, r.email, r.guidance, r.browsers, r.apps, moves)
    return state, questions


def fidelity(case: Case) -> list[str]:
    """What the current code builds differently from what was sent: 'state', or a question's name.
    Empty when the case reproduces exactly, which is how a rebuild is trusted."""
    state, questions = request(case)
    differs = ["state"] if state != case.state else []
    differs += [
        name for name, criteria in case.criteria.items() if name not in questions or dict(questions[name].criteria) != criteria
    ]
    return differs


def wire(value) -> int:
    """Bytes on the wire, as the client encodes a request body: compact, UTF-8."""
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())


def sizes(state: dict, questions: dict[str, Choice]) -> dict[str, int]:
    """A request's bytes by part. A question with one label is answered in code and not sent."""
    sent = {name: q for name, q in questions.items() if not is_settled(q)}
    parts = {"state": wire(state), "items_in_state": wire(state.get("screen_items_in_reading_order", []))}
    parts.update({f"q_{name}": wire(q.wire()) for name, q in sent.items()})
    parts["total"] = wire({"model": "m", "state": state, "questions": {name: q.wire() for name, q in sent.items()}})
    return parts

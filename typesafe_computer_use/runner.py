"""The step loop and the run folder."""

from __future__ import annotations

import json
import re
import time
import traceback
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image

from .actions import Context, Look, last_look, moved, perform, wait, writer_scroll
from .calls import Calls, MeteredClassifier, MeteredWriter
from .config import (
    CHANGES_NOUL,
    DEFAULT_DELAY,
    DEFAULT_HANDOFFS,
    DEFAULT_MIN_CONFIDENCE,
    DEFAULT_READ_ONLY_CONFIDENCE,
    DEFAULT_STEPS,
    MAX_OPTIONS,
    MOVES_NOUL,
    PLAN_NOUL,
    READ_ONLY_NOUL,
    answer_model,
    moves_override,
    plan_override,
    writer_model,
)
from .decide import (
    STOP_KINDS,
    Decision,
    browser_names,
    changes_something,
    decide,
    kind_criteria,
    needs_moves,
    needs_plan,
    offscreen_records,
    read_only,
    row_mates,
)
from .decisions import DecisionClient, DecisionError
from .events import Events
from .models import Abort, EarlierTask, Field, Guidance, Item, Screen, Signature, same_screen, signature
from .perception import OcrCache, capture, perceive
from .platform_adapter import desktop
from .report import Log, annotate, ax_count, render_payload, top
from .timing import format_timing, phase, summarize
from .writer import Answer, Fill, WriterError, compose_answer, compose_plan, compose_text

# Two ways a run stalls, both read off the screen rather than off the history line, because an
# action's description says what was attempted and only the next capture says what came of it.
MAX_IDLE = 3  # consecutive actions that left the screen as it was: refusals, waits on a spinner, scrolls at the bottom
MAX_REPEATS = 2  # consecutive actions already taken on the same screen earlier in the run: a cycle, or a click that does nothing
MAX_REVISITS = 2  # consecutive navigations to the place the action before already went to, whatever the page reads
NAVIGATIONS = ("use_browser", "open_app")  # the actions that go to a place, not to something on the screen
MAX_STALLS = 3  # stalls with no new page between them; the last is final, since two focuses from the writer did not free the run
SETTLE_LOOK = 0.25  # between two looks at a screen that may still be moving; each look is a capture of its own
# The most a kind of action waits to settle, below `--delay`, for the kinds whose own check already looked.
# No scroll on the saved runs that settled on its own took past 1.7 s, and a 1.5 s limit still lets the look
# that ends there start; past it, a scrolled screen that never holds still is something playing beside it.
SETTLE_CAPS = {"scroll_down": 1.5, "scroll_up": 1.5}
REFUSED = re.compile(r"[a-z_]+ refused: ")  # an action that did nothing; one that closed a popup first starts otherwise
EARLIER_LINES = 600  # lines of text from the screens before the last one that the answer may also be read from
MAX_QUESTIONS = 3  # questions the writer may put to the user in one run; an empty reply ends the asking sooner
FOCUS_LEAD = 2.0  # how many times likelier the item a focus names must be than another item of the same text
# The text a focus quotes: in curly or straight quotes, but not an apostrophe ("the browser's 'Tab search'").
QUOTED = re.compile(r"\u201c(.+?)\u201d|\"(.+?)\"|\u2018(.+?)\u2019|(?<!\w)'(.+?)'(?!\w)")
WAITING = "wait for the screen to finish loading"  # the focus a handoff records when the writer called for a wait
HANDOFF_FILE = "handoff.json"  # what a run that ended short of the goal leaves for an outer agent to go on from
HANDOFF_RAW = "handoff-raw.png"  # the screen it ended on, as captured
# The kinds of action a run with `ask` or `look` permissions checks before taking: the ones that land on
# something and can change it. A scroll, a wait, Escape, going back, and going to a site or an app only
# move the run, and a right click or a selection only shows what an item offers.
GUARDED_KINDS = frozenset(
    {
        "click_item",
        "double_click_item",
        "drag_item",
        "press_offscreen",
        "press_shortcut",
        "type_text",
        "type_email",
        "press_enter",
    }
)
YES = frozenset({"y", "yes", "yeah", "yep", "ok", "okay", "sure", "go", "go ahead", "allow", "do it"})
# What the writer is told the run may do, for the permissions other than `full`.
MAY_DO = {
    "ask": (
        "the user must allow each action that would change something (send, buy, save, post, submit, delete) "
        "before it is taken; the run asks them itself, so a focus may name such an action"
    ),
    "look": (
        "only look: open, read, search and scroll, never take an action that would change something (send, buy, "
        "save, post, submit, delete, add to a cart); never give a focus that needs one"
    ),
}

# The outcomes the writer is handed, each in words it can pass on. A dry run took no action and
# an abort is the user's own stop, so neither has anything to report.
STOPPED = {
    "done": "the classifier judged the goal already achieved on this screen",
    "nothing helps": "the classifier found nothing on this screen that helps with the goal",
    "low confidence": "the classifier was not confident enough in any next action",
    "stalled": "the last actions changed nothing",
    "stuck": (
        "the agent is stuck: its last actions changed nothing, as they did twice before on these same pages, "
        "and the focus given each time did not help, so the run ends with this answer"
    ),
    "unfollowed": (
        "the classifier could not act on the focus you gave last time, and the screen has not changed since, "
        "so the run ends with this answer"
    ),
    "step limit": "the run used every step it was allowed",
    "look only": (
        "the next action would have changed something, and this run may only look, so it was not taken: "
        "answer from what is on screen, or give a focus that only opens or reads"
    ),
    "declined": (
        "the next action would have changed something, and the user did not allow it, so it was not taken; "
        "what they said is under user_said"
    ),
    "no decision": "the decision model gave no usable answer for this screen: it refused, failed, or was unreachable",
}


def goal_achieved(state) -> bool | None:
    """The writer's verdict, else False for a run that stopped on its own without one.

    An abort, a dry run and a crash reached no verdict either way. A "done" is the classifier's
    own verdict that the goal was met, which only the writer's answer can carry.
    """
    if state.answer:
        return state.answer.achieved
    return False if state.outcome in STOPPED and state.outcome != "done" else None


@dataclass
class RunConfig:
    goal: str
    out: Path
    act: bool = False
    steps: int = DEFAULT_STEPS
    min_confidence: float = DEFAULT_MIN_CONFIDENCE
    read_only_confidence: float = DEFAULT_READ_ONLY_CONFIDENCE  # the floor instead, for a goal that only looks
    delay: float = DEFAULT_DELAY
    handoffs: int = DEFAULT_HANDOFFS  # stops the writer may send the classifier back from; 0 makes every stop final
    permissions: str = "full"  # full, ask or look: what the run may do without asking (see config.permissions)
    image: Path | None = None  # replay a saved capture (never acts)
    app: str | None = None  # frontmost app to report during replay
    url: str | None = None  # browser URL to report during replay
    earlier: tuple[EarlierTask, ...] = ()  # the tasks given before this one in the same session, for the writer
    # Start each capture's OCR on a thread of its own while the capture asks for the app, window,
    # field, and URL (see `OcrCache.read_ahead`). Worth it where those questions are slow, as over an
    # OSWorld VM; off for this machine, whose own are quick.
    read_ahead: bool = False

    @property
    def replay(self) -> bool:
        return self.image is not None


@dataclass(frozen=True)
class Handoff:
    """One stop the writer sent the classifier back from."""

    step: int
    outcome: str  # why the classifier stopped
    focus: str  # what the writer sent it back to do
    actions: int  # how many actions the run had taken by then, so a focus that led to none can be told
    said: str = ""  # what the writer told the user then, which may quote a screen since dropped from earlier_screens


Clicked = tuple[str, str | None, Field]  # app, URL, and the box a click on page text landed in


@dataclass
class RunState:
    history: list[str] = field(default_factory=list)
    timings: list[dict[str, float]] = field(default_factory=list)
    idle: int = 0  # actions in a row that changed nothing on screen
    repeats: int = 0  # actions in a row already taken on the same screen
    revisits: int = 0  # navigations in a row to the place the one before went to
    navigated: str | None = None  # the last action when it was a navigation, so the next can be told a revisit
    stalls: int = 0  # stalls since the run last reached a page it had not been on
    pages: set[tuple[str, str | None]] = field(default_factory=set)  # every (app, URL) the run has shown
    last: Signature | None = None  # the screen the last action was taken on
    seen: list[tuple[Signature, str | None]] = field(
        default_factory=list
    )  # every screen acted on, with the action; None for a wait
    outcome: str = "crashed"  # every way out of the loop names its own; only an exception leaves this
    ocr_cache: OcrCache = field(default_factory=OcrCache)  # carries one step's OCR into the next
    view: tuple[Screen, list[Item]] | None = None  # the latest capture, until an action makes it stale
    clicks: dict[tuple, str] = field(default_factory=dict)  # (app, page, item text) -> what clicking it did
    pending_click: tuple | None = None  # the last click, until the next capture shows what it did
    answer: Answer | None = None  # the writer's latest; the last one is the run's answer
    answered: Signature | None = None  # the screen the writer's latest answer was read from
    guidance: Guidance = field(default_factory=Guidance)  # the writer's focus and the user's replies, as they stand
    handoffs: list[Handoff] = field(default_factory=list)
    calls: Calls = field(default_factory=Calls)  # requests to each model, over the whole run
    clicked: Clicked | None = None  # the last action's click on page text, for the screen right after it
    read_only: bool = False  # the goal only asks to find something out, so the lower floor applies
    moves: bool = False  # the goal needs a move beyond clicking and typing, so the run is offered the moves that are
    moves_by: str = "gate"  # who settled it: the gate's question about the goal, or CLICKER_MOVES
    plan_by: str = "gate"  # who settled whether the writer was asked for a plan: the gate, or CLICKER_PLAN
    handed_on: bool = False  # the run ended short of the goal and wrote `handoff.json` for an outer agent
    allowed: set[tuple] = field(default_factory=set)  # (app, page, action) the user allowed, so the same one is not asked twice
    held: list[dict] = field(default_factory=list)  # each action the permissions held, and what came of it


def run(cfg: RunConfig, ctx_factory, events: Events | None = None) -> RunState:
    """Drive the loop. ctx_factory(typesafe, history) builds the action Context.

    With `events`, the run reports to a front end as it goes instead of printing (see events.py).
    """
    cfg.out.mkdir(parents=True, exist_ok=True)
    log = Log(cfg.out / "run.log", events)
    log(f"run folder: {cfg.out}")
    log.event("run", folder=str(cfg.out), act=cfg.act)
    if cfg.act:
        log(f"driving the machine. abort: {desktop.abort_hint()}.")

    state = RunState(guidance=Guidance(earlier=cfg.earlier))
    started = time.time()
    models: dict[str, str | None] = {}
    try:
        with DecisionClient() as typesafe:
            ctx = metered(ctx_factory(typesafe, state.history), state.calls)
            models = configured_models(typesafe, ctx)
            log(f"models: decisions {models['decisions']}, writer {models['writer']}, answer {models['answer']}")
            state.read_only = goal_only_looks(ctx, cfg.goal, log)
            state.moves = goal_needs_moves(ctx, cfg.goal, log)
            state.moves_by = "CLICKER_MOVES" if moves_override() is not None else "gate"
            state.plan_by = "CLICKER_PLAN" if plan_override() is not None else "gate"
            if goal_needs_plan(ctx, cfg.goal, log):
                state.guidance = replace(state.guidance, plan=plan_for(ctx, cfg.goal, state.guidance, log))
            for step in range(1, cfg.steps + 1):
                ctx = replace(ctx, guidance=state.guidance)  # a handoff sets the focus, and the action it asked for spends it
                if run_step(cfg, ctx, state, step, log):
                    continue
                if not hand_off(cfg, ctx, state, step, log):
                    break
            else:
                log(f"\nstopped after {cfg.steps} steps")
                state.outcome = "step limit"
                hand_off(cfg, ctx, state, cfg.steps, log)
            write_handoff(cfg, ctx, state, log)
    except (KeyboardInterrupt, Abort) as e:
        state.outcome = f"aborted ({str(e) or 'Ctrl-C'})"  # a bare KeyboardInterrupt is truthy but prints as ""
        log(f"\n{state.outcome} after {len(state.history)} actions")
    except Exception:
        # The menu bar app shows stderr only for a run that never began, so the folder keeps why.
        log(f"\ncrashed after {len(state.history)} actions:\n{traceback.format_exc().rstrip()}")
        raise
    finally:
        summary = {
            "goal": cfg.goal,
            "act": cfg.act,
            "steps_taken": len(state.history),
            "outcome": state.outcome,
            "answer": state.answer.text if state.answer else None,
            "goal_achieved": goal_achieved(state),
            "seconds": round(time.time() - started, 1),
            "models": models,
            "read_only": state.read_only,
            "permissions": cfg.permissions,
            "held": state.held,
            "moves": state.moves,
            "moves_by": state.moves_by,
            "plan": state.guidance.plan,
            "plan_by": state.plan_by,
            "calls": state.calls.summary(),
            "usage": state.calls.tokens(),
            "usage_by_role": state.calls.by_role(),
            "cost": state.calls.cost(),
            "ended_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "handoffs": [asdict(h) for h in state.handoffs],
            "handoff": HANDOFF_FILE if state.handed_on else None,
            "questions": [asdict(e) for e in state.guidance.exchanges],
            "earlier_tasks": [asdict(t) for t in cfg.earlier],
            "timing": summarize(state.timings),
            "history": state.history,
            "config": {k: str(v) for k, v in asdict(cfg).items()},
        }
        (cfg.out / "run.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        log(f"{state.calls.line()}  handoffs {len(state.handoffs)}  questions {len(state.guidance.exchanges)}")
        log(f"run folder: {cfg.out}")
        log.event("end", folder=str(cfg.out), why=STOPPED.get(state.outcome), **summary)
    return state


def write_handoff(cfg: RunConfig, ctx: Context, state: RunState, log: Log) -> None:
    """A run that stopped short of the goal leaves its story for an outer agent to take over from.

    The writer can send the classifier back, but it never takes the wheel itself, so a run it
    could not free ends with an answer and nothing more. `handoff.json` is the rest: what the
    agent did and where, why it stopped, what the writer tried, the screens it passed and the one
    it ended on, and the moves it had, so a model that can do more starts from this screen and
    not from the goal alone. It holds screen text, so it stays in the run folder, as the captures
    do; a credential is never typed by the run, so none is in the actions.

    Only a run that stopped (see STOPPED) with the goal not achieved writes it. A dry run, an
    abort and a crash reached no verdict, and an achieved goal leaves nothing to take over.
    """
    if state.outcome not in STOPPED or goal_achieved(state) is not False:
        return
    # The run has already ended with its outcome; a packet that cannot be written must not turn
    # that into a crash, so the failure is logged and `run.json` says no packet was left.
    try:
        raw = None
        if state.view is not None:
            state.view[0].image.save(cfg.out / HANDOFF_RAW)  # the screen in memory, not a new capture
            raw = HANDOFF_RAW
        packet = handoff_packet(cfg, ctx, state, raw)
        (cfg.out / HANDOFF_FILE).write_text(json.dumps(packet, indent=2), encoding="utf-8")
    except Exception:
        log(f"handoff not written:\n{traceback.format_exc().rstrip()}")
        return
    state.handed_on = True
    log(f"handoff: {cfg.out / HANDOFF_FILE}")
    log.event("handoff", file=str(cfg.out / HANDOFF_FILE), **packet)


def handoff_packet(cfg: RunConfig, ctx: Context, state: RunState, raw: str | None) -> dict:
    """What `handoff.json` holds; see `write_handoff` and docs/run-folder.md."""
    now = signature(*state.view) if state.view is not None else None
    final = now or state.last
    # Every action has a screen in `state.seen`, the one it was taken on, in the same order.
    on = [seen for seen, _ in state.seen]
    # The screen each action led to: the one the next action was taken on, and for the last, the one
    # the run ended on; none when an action ran and nothing read the screen after it.
    after = [*on[1:], now]
    # Paired by position, so a change that records an action without its screen fails the test that
    # checks the pairing rather than a user's run.
    actions = [
        {
            "action": what,
            "app": before[0],
            "url": before[1],
            "then": None if then is None else {"app": then[0], "url": then[1], "changed_screen": not same_screen(before, then)},
        }
        for what, before, then in zip(state.history, on, after, strict=False)
    ]
    answer = state.answer
    return {
        "goal": cfg.goal,
        "outcome": state.outcome,
        "why": STOPPED[state.outcome],
        "answer": answer.text if answer else None,
        "plan": state.guidance.plan,
        "last_focus": (answer.focus or None) if answer else None,
        "actions": actions,
        "handoffs": [asdict(h) for h in state.handoffs],
        "questions": [asdict(e) for e in state.guidance.exchanges],
        "earlier_screens": earlier_screens(state, final) if final is not None else [],
        "current_screen": None
        if now is None
        else {"app": now[0], "url": now[1], "field": now[2], "text": [text for text, _ in now[3]], "raw": raw},
        "moves": [
            kind
            for kind in kind_criteria(ctx.browser, ctx.email, True, ctx.browsers, ctx.apps, state.moves)
            if kind not in STOP_KINDS
        ],
        "read_only": state.read_only,
        "permissions": cfg.permissions,
    }


def configured_models(typesafe: DecisionClient, ctx: Context) -> dict[str, str | None]:
    """The models this run asks, for its folder. The CLI prints them, but a front end shows those
    lines nowhere, and the token count names only models that replied: a run whose every decision
    was refused showed no decision model at all."""
    return {
        "decisions": typesafe.endpoint.model,
        "writer": writer_model() if ctx.writer is not None else None,
        "answer": answer_model() if ctx.writer is not None else None,
    }


def goal_only_looks(ctx: Context, goal: str, log: Log) -> bool:
    """Whether the goal only asks to find something out, by the decision model. Unsure, or no
    answer, is a goal that may change something: the higher floor is the safe one."""
    try:
        p = read_only(ctx.typesafe, goal)
    except DecisionError as e:
        log(f"read-only: unknown ({e}), so the floor stays")
        return False
    looks = p >= READ_ONLY_NOUL
    log(f"read-only: {'yes' if looks else 'no'} ({p:.2f})")
    return looks


def goal_needs_moves(ctx: Context, goal: str, log: Log) -> bool:
    """Whether the goal needs a move beyond clicking and typing, by the decision model. Unsure, or no
    answer, is a goal that needs none: the requests stay as they were, which is the safe side.
    CLICKER_MOVES=on or off settles it without asking, for a run that must not depend on the guess."""
    forced = moves_override()
    if forced is not None:
        log(
            f"moves: {'offered' if forced else 'not offered'} (CLICKER_MOVES={'on' if forced else 'off'}, so the goal is not asked about)"
        )
        return forced
    try:
        p = needs_moves(ctx.typesafe, goal)
    except DecisionError as e:
        log(f"moves: unknown ({e}), so none are offered")
        return False
    needs = p >= MOVES_NOUL
    log(f"moves: {'offered' if needs else 'not offered'} ({p:.2f})")
    return needs


def goal_needs_plan(ctx: Context, goal: str, log: Log) -> bool:
    """Whether the writer is asked for a plan, by the decision model. Unsure, no answer, or no writer is a
    run without one: the requests stay as they were. CLICKER_PLAN=on or off settles it without asking."""
    if ctx.writer is None:
        return False
    forced = plan_override()
    if forced is not None:
        log(
            f"plan: {'asked for' if forced else 'not asked for'} (CLICKER_PLAN={'on' if forced else 'off'}, so the goal is not asked about)"
        )
        return forced
    try:
        p = needs_plan(ctx.typesafe, goal)
    except DecisionError as e:
        log(f"plan: unknown ({e}), so none is asked for")
        return False
    needs = p >= PLAN_NOUL
    log(f"plan: {'asked for' if needs else 'not asked for'} ({p:.2f})")
    return needs


def plan_for(ctx: Context, goal: str, guidance: Guidance, log: Log) -> str | None:
    """The writer's plan for the goal, or None when it declined or failed: the run goes on without one."""
    try:
        plan = compose_plan(ctx.writer, goal, guidance)
    except WriterError as e:
        log(f"plan: none ({e})")
        return None
    if not plan:
        log("plan: none (the writer saw no plan to make)")
        return None
    log("plan:\n" + "\n".join(f"  {line}" for line in plan.splitlines() if line.strip()))
    return plan


def metered(ctx: Context, calls: Calls) -> Context:
    """The same context, with every request to either model counted."""
    return replace(
        ctx,
        typesafe=MeteredClassifier(ctx.typesafe, calls),
        writer=MeteredWriter(ctx.writer, calls) if ctx.writer is not None else None,
    )


def hand_off(cfg: RunConfig, ctx: Context, state: RunState, step: int, log: Log) -> bool:
    """The classifier stopped: hand the run to the writer. True when the writer handed it back.

    The classifier can stop on the right page but cannot say what the page says, and it can stop
    short because one sentence of goal does not say which of two good moves comes first. The writer
    reads the screen and answers for the user either way. When the goal is not reached it may also
    name a focus, which sends the classifier back to work with `state.guidance` saying what on, or
    a question, which goes to the user first; the writer then reads the same screen again with the
    reply. Each reply is new information and each focus must lead to an action, so the exchange
    cannot go round on itself: a focus the classifier could not act on, on the screen the answer
    that gave it was read from, ends the run, and a stall with no new page since the last two is
    final (see `stuck`). The writer reads that screen once more for the last answer, since the one
    that gave the focus was written to send the run on ("I'll open it") and told the user nothing
    about where it ended. A screen that changed on its own, as a page still loading does, is read
    again as any stop is: the last answer describes a screen that is gone.

    The writer may also find the screen still loading. The classifier ranks a click on what has
    already drawn over waiting for the rest, so the run waits itself, as a wait the classifier
    chose would, and the classifier reads the screen once it has loaded.
    """
    stuck(state, log)
    if state.outcome in STOPPED and unfollowed(state):
        log(f"  the focus led to no action: {state.handoffs[-1].focus}")
        state.outcome = "unfollowed"
    stopped = STOPPED.get(state.outcome)
    if stopped is None:
        return False
    if ctx.writer is None:
        log("\nno answer: the writer is disabled (set OPENROUTER_API_KEY, ANTHROPIC_API_KEY or CLICKER_WRITER_BASE_URL)")
        return False

    may_resume = step < cfg.steps and len(state.handoffs) < cfg.handoffs and state.outcome not in ("stuck", "unfollowed")
    reviews: list[dict] = []
    while True:
        can_ask = may_resume and ctx.ask is not None and len(state.guidance.exchanges) < MAX_QUESTIONS
        started = time.perf_counter()
        try:
            answer = review(cfg, ctx, state, stopped, can_ask)
        except WriterError as e:
            log(f"\nno answer: the writer failed ({e})")
            return False
        state.answer = answer
        seconds = time.perf_counter() - started
        record = {"outcome": state.outcome, "seconds": round(seconds, 3), **asdict(answer), "reply": None, "handed_back": False}
        reviews.append(record)
        try:
            resuming = may_resume and not answer.achieved
            if resuming and can_ask and answer.question:
                log(f"\nreview ({verdict(answer)}, {seconds:.1f}s):\n  {answer.text}\n  the writer asks: {answer.question}")
                reply = ctx.ask(answer.question).strip()
                record["reply"] = reply
                log(f"  > {reply}", echo=False)  # the terminal already shows what was typed
                if not reply:
                    log("  no reply, so the answer stands")
                    return False
                state.guidance = state.guidance.heard(answer.question, reply)
                if cfg.act and not cfg.replay and state.view is not None:
                    desktop.activate(state.view[0].app)  # answering took the terminal to the front; put the work back there
                continue
            if resuming and answer.wait:
                log(f"\nreview ({verdict(answer)}, {seconds:.1f}s):\n  {answer.text}\n  the screen is still loading; waiting")
                log.event("focus", text=answer.text, focus=WAITING)
                record["handed_back"] = True
                state.handoffs.append(Handoff(step, state.outcome, WAITING, len(state.history), answer.text))
                state.guidance = state.guidance.followed()  # a focus given before the screen had loaded
                state.idle = state.repeats = state.revisits = 0
                if cfg.act and not cfg.replay:
                    wait_for_screen(cfg, ctx, state, log)
                return True
            if resuming and answer.scroll:
                where = f" over {answer.scroll_over!r}" if answer.scroll_over else ""
                log(
                    f"\nreview ({verdict(answer)}, {seconds:.1f}s):\n  {answer.text}\n  the writer scrolls {answer.scroll}{where}"
                )
                log.event("focus", text=answer.text, focus=f"Scroll {answer.scroll}{where}")
                record["handed_back"] = True
                state.handoffs.append(
                    Handoff(step, state.outcome, f"scroll {answer.scroll}{where}", len(state.history), answer.text)
                )
                state.guidance = state.guidance.followed()  # a focus from before the scroll is about the old screen
                state.idle = state.repeats = state.revisits = 0
                if cfg.act and not cfg.replay:
                    scroll_for_writer(cfg, state, answer, log)
                return True
            if resuming and answer.focus:
                log(
                    f"\nreview ({verdict(answer)}, {seconds:.1f}s):\n  {answer.text}\n  back to the classifier, focus: {answer.focus}"
                )
                log.event("focus", text=answer.text, focus=answer.focus)
                record["handed_back"] = True
                state.handoffs.append(Handoff(step, state.outcome, answer.focus, len(state.history), answer.text))
                state.guidance = state.guidance.focused(answer.focus)
                state.idle = state.repeats = state.revisits = 0  # the stall was under the old focus; the new one starts clean
                return True
            log(f"\nanswer ({verdict(answer)}, {seconds:.1f}s):\n  {answer.text}")
            log.event("answer", text=answer.text, achieved=answer.achieved)
            return False
        finally:
            (cfg.out / f"step-{step:03d}-review.json").write_text(json.dumps(reviews, indent=2), encoding="utf-8")


def unfollowed(state: RunState) -> bool:
    """The writer's last focus led to no action, on the screen the answer that gave it was read from."""
    return bool(
        state.handoffs
        and state.handoffs[-1].actions == len(state.history)
        and state.answered is not None
        and state.view is not None
        and same_screen(state.answered, signature(*state.view))
    )


def wait_for_screen(cfg: RunConfig, ctx: Context, state: RunState, log: Log) -> None:
    """Take the wait the writer called for as a wait the classifier chose is taken: an action in the
    history, never one to repeat (see `repeating`), with no settle after it (see `settle_action`)."""
    screen, items = state.view
    what = wait(screen, items, ctx)
    state.view = None
    state.history.append(what)
    state.seen.append((state.last, None))
    log(f"  did: {what}")
    log.event("action", text=what, actions=len(state.history))


def scroll_for_writer(cfg: RunConfig, state: RunState, answer: Answer, log: Log) -> None:
    """Take the scroll the writer called for as an action of the run's own, as `wait_for_screen`
    takes its wait, and settle before the next step reads the screen it ends on."""
    screen, items = state.view
    what = writer_scroll(answer.scroll, answer.scroll_over, screen, items)
    state.view = None
    state.history.append(what)
    state.seen.append((state.last, None))
    log(f"  did: {what}")
    log.event("action", text=what, actions=len(state.history))
    kind = "scroll_up" if answer.scroll in ("up", "top") else "scroll_down"
    settle_action(screen, cfg.delay, kind, what, last_look())


def stuck(state: RunState, log: Log) -> None:
    """Count a stall, and call the run stuck once it is the third with no new page between them.

    A stall hands the run to the writer like any stop, and its focus usually frees the classifier.
    When the classifier stalls again on the pages it was already on, the focus did not help, and
    each further round costs a writer call and a few futile actions. On OSWorld's Chrome tasks every
    run that stalled a third time on the same pages failed all the same, up to 210 s later, and no
    solved run stalled more than twice. A new page is the progress that starts the count again, so
    a long task that stalls now and then on its way is not cut short.
    """
    if state.outcome != "stalled":
        return
    state.stalls += 1
    if state.stalls >= MAX_STALLS:
        log(f"  stuck: {state.stalls} stalls without reaching a new page; the run ends here")
        state.outcome = "stuck"


def verdict(answer: Answer) -> str:
    return "goal achieved" if answer.achieved else "goal not achieved"


def review(cfg: RunConfig, ctx: Context, state: RunState, stopped: str, can_ask: bool) -> Answer:
    """Have the writer read the screen the classifier stopped on.

    The last step's capture serves when nothing acted after it. An action makes it stale, so the
    screen is captured again, and saved so the answer can be checked against what it was read from.
    """
    if state.view is None:
        desktop.check_abort()
        screen = capture(cfg.image, cfg.app, cfg.url, ctx.browser, browsers=ctx.browsers)
        screen.image.save(cfg.out / "answer-raw.png")
        state.view = (screen, perceive(screen, MAX_OPTIONS, cfg.goal))
    screen, items = state.view
    state.answered = signature(screen, items)
    earlier = earlier_screens(state, state.answered)
    earlier_stops = [
        {"after_action": h.actions, "why": STOPPED[h.outcome], "you_said": h.said, "focus_given": h.focus} for h in state.handoffs
    ]
    return compose_answer(
        ctx.writer,
        cfg.goal,
        screen,
        items,
        state.history,
        stopped,
        earlier,
        state.guidance,
        earlier_stops,
        can_ask,
        state.moves,
        MAY_DO.get(cfg.permissions),
    )


def earlier_screens(state: RunState, final: Signature, budget: int = EARLIER_LINES) -> list[dict]:
    """The distinct screens the run passed through before the one it ended on, oldest first.

    The goal may ask for something that was on the way (a price on the listing, not on the checkout),
    and the run's own captures are the only place the answer may come from. A screen seen twice
    is sent once. The newest screens are kept whole and the oldest dropped once the line budget
    is spent, since the writer reads all of it in one call.

    Each screen says the action that reached it, `reached_by`, and holds only the lines that neither the
    screen it ended on, sent whole beside them, nor a newer screen of these already holds; a screen with
    none left is not sent. A run that opened forty
    conversations from one inbox passed screens that each held the whole inbox list, the tab strip
    and the menus beside one conversation: the line budget held six of them, and with every name on
    every screen and no address that names anyone, the answer gave one person's words to another.
    """
    shown = {text for text, _ in final[3]}
    out: list[tuple[Signature, str | None, list[str]]] = []
    lines_left = budget
    for k in range(len(state.seen) - 1, -1, -1):
        seen = state.seen[k][0]
        if same_screen(seen, final) or any(same_screen(seen, kept) for kept, _, _ in out):
            continue
        text = [line for line, _ in seen[3] if line not in shown]
        if not text:
            continue
        shown.update(text)
        lines_left -= len(text)
        if lines_left < 0:
            break
        # The last action taken on another screen: a wait, or a click that changed nothing, did not reach it.
        reached = next((what for on, what in reversed(state.seen[:k]) if what is not None and not same_screen(on, seen)), None)
        out.append((seen, reached, text))
    return [
        {"app": app, "url": url, **({"reached_by": reached} if reached else {}), "text": text}
        for (app, url, _, _), reached, text in reversed(out)
    ]


def run_step(cfg: RunConfig, ctx: Context, state: RunState, step: int, log: Log) -> bool:
    desktop.check_abort()
    log.event("step", step=step)
    timing: dict[str, float] = {}
    started = time.perf_counter()
    cache = None if cfg.replay else state.ocr_cache
    with phase(timing, "capture"):
        screen = capture(
            cfg.image, cfg.app, cfg.url, ctx.browser, timing, ahead=cache if cfg.read_ahead else None, browsers=ctx.browsers
        )
    screen = with_clicked_field(screen, state.clicked, browser_names(ctx.browser, ctx.browsers))
    state.clicked = None
    items = perceive(screen, MAX_OPTIONS, cfg.goal, timing, cache, apart=state.moves)
    state.view = (screen, items)
    remember_clicks(state, screen, items)
    if not screen_moved(state, screen, items, log):
        return False
    tried = tried_here(state)
    prefix = cfg.out / f"step-{step:03d}"  # three digits, so a run of 100 steps still lists in order
    screen.image.save(prefix.with_name(prefix.name + "-raw.png"))
    prefix.with_name(prefix.name + "-payload.txt").write_text(
        render_payload(
            cfg.goal,
            screen,
            items,
            state.history,
            ctx.browser,
            ctx.email,
            tried,
            ctx.guidance,
            ctx.browsers,
            ctx.apps,
            state.moves,
        ),
        encoding="utf-8",
    )

    try:
        with phase(timing, "decide"):
            decision = decide(
                ctx.typesafe,
                cfg.goal,
                screen,
                items,
                state.history,
                ctx.browser,
                ctx.email,
                tried,
                ctx.guidance,
                ctx.browsers,
                ctx.apps,
                state.moves,
            )
    except DecisionError as e:
        # A refusal or an outage is not a guess to act on: the writer reads this screen instead.
        log(f"\nstep {step}: no decision ({e})")
        state.outcome = "no decision"
        return False
    by_index = {str(it.index): it for it in items}
    annotate(
        screen,
        items,
        decision.item.choice if decision.pointing or decision.dragging else decision.chosen,
        prefix.with_suffix(".png"),
        dropped_on=decision.target.choice if decision.dragging else None,
    )

    field_desc = (
        f" field={'clicked' if screen.field.clicked else screen.field.role}:{screen.field.label!r}" if screen.field else ""
    )
    log(
        f"\nstep {step}: app={screen.app!r}{field_desc}{keys_desc(screen)} url={screen.url!r} items={len(items)} ax={ax_count(items)} "
        f"offscreen={len(screen.offscreen)} kind={decision.kind.choice} ({decision.kind.confidence:.2f}) "
        f"site={decision.site.choice}"
        + (f" browser={decision.browser.choice!r} ({decision.browser.confidence:.2f})" if decision.browser is not None else "")
        + (f" open={decision.app.choice!r} ({decision.app.confidence:.2f})" if decision.app is not None else "")
        + (
            f" shortcut={decision.shortcut.choice!r} ({decision.shortcut.confidence:.2f})"
            if decision.shortcut is not None
            else ""
        )
        + (f" target={decision.target.choice!r} ({decision.target.confidence:.2f})" if decision.target is not None else "")
        + (f" refused={decision.refused}, asked again without it" if decision.refused else "")
    )
    for key, p in top(decision.kind, 4):
        log(f"  {p:5.2f}  {key}")
    if decision.item is not None:
        log(f"  item ({decision.item.confidence:.2f}):")
        for key, p in top(decision.item, 4):
            log(f"  {p:5.2f}  [{key}] {by_index[key].text!r}")
    if decision.offscreen is not None:
        log(f"  offscreen ({decision.offscreen.confidence:.2f}):")
        for key, p in top(decision.offscreen, 3):
            log(f"  {p:5.2f}  [{key}] {screen.offscreen[int(key)].label!r}")

    keep_going = resolve(cfg, ctx, state, screen, items, decision, timing, log)
    timing.setdefault("act", 0.0)
    if state.view is None:  # an action ran: let the screen settle before the next step, or the answer, reads it
        with phase(timing, "settle"):
            settle_action(screen, cfg.delay, decision.kind.choice, state.history[-1], last_look())
    timing["total"] = round(time.perf_counter() - started, 3)
    state.timings.append(timing)

    prefix.with_name(prefix.name + "-answers.json").write_text(
        json.dumps(answers(decision, screen, items, timing, tried, state), indent=2), encoding="utf-8"
    )
    log(f"  files: {prefix.name}-raw.png, {prefix.name}.png, {prefix.name}-payload.txt, {prefix.name}-answers.json")
    log(format_timing(timing))
    return keep_going


def settle_action(before: Screen, limit: float, kind: str, what: str, look: Look | None) -> None:
    """Settle after an action of `kind` that `what` describes, given what its own check saw.

    Over 604 saved steps settle was a third of all step time, and an action that is already done
    waited out the whole limit like one that is not. So no settle follows a wait, which is itself
    the time to wait; a refusal, which did nothing; or a scroll its own check saw change nothing
    (a list at its end). A check that saw the change is the settle's first look. A press that showed
    nothing is not one of these: a pointer click followed it, and its effect has not been looked at.
    """
    if kind == "wait" or REFUSED.match(what) or (look is not None and not look.changed):
        return
    settle(before, min(limit, SETTLE_CAPS.get(kind, limit)), look.image if look is not None else None)


def settle(before: Screen, limit: float, seen: Image.Image | None = None) -> None:
    """Wait for what an action did to finish showing, for `limit` seconds at most.

    A fixed pause cost every action the whole limit, 20 s of a 116 s run on Google Flights, though
    most pages repaint in a fraction of it. So the display is looked at instead: once it differs
    from the capture the action was decided on and then holds still for one look, it has settled.
    A screen that has not changed at all may be waiting on the network, and one that never holds
    still is loading or playing something, so both get the whole limit, as before. No limit means
    no looks, as on OSWorld, where each one would be a round trip. `seen` is a capture the action's
    own check already took after acting: it counts as the first look.
    """
    if limit <= 0:
        return
    end = time.monotonic() + limit
    last = seen
    while (left := end - time.monotonic()) > 0:
        desktop.sleep_watching(min(SETTLE_LOOK, left))
        now = desktop.screenshot()
        if last is not None and moved(before.image, now, before.scale) and not moved(last, now, before.scale):
            return
        last = now


def resolve(
    cfg: RunConfig,
    ctx: Context,
    state: RunState,
    screen: Screen,
    items: list[Item],
    decision: Decision,
    timing: dict[str, float],
    log: Log,
) -> bool:
    """Apply the stop rules, then the action. True to keep looping."""
    if decision.stops:
        log(f"  model says {decision.kind.choice!r}; stopping")
        state.outcome = "done" if decision.kind.choice == "done" else "nothing helps"
        return False
    # The low floor is for a goal where a wrong click only opens the wrong page. A shortcut is not that: cut, paste
    # and close tab are not always undone, and a goal that only looks things up is as likely as any to open the moves.
    floor = (
        cfg.read_only_confidence
        if state.read_only and not (decision.pressing_shortcut or decision.pointing)
        else cfg.min_confidence
    )
    if decision.confidence < floor:
        named = named_by_focus(decision, items, state.guidance.focus)
        if named is None or decision.kind.confidence < floor:
            log(f"  confidence {decision.confidence:.2f} below {floor}; stopping")
            state.outcome = "low confidence"
            return False
        log(f"  confidence {decision.confidence:.2f} below {floor}, but the focus names {named!r}; going ahead")
    if not cfg.act or cfg.replay:
        log(f"  would do: {decision.chosen}. dry run (pass --act without --image to drive the machine)")
        log.event("would", text=intended(decision, screen, items))
        state.outcome = "dry run"
        return False

    if decision.kind.choice == "type_text":
        # What to write may have been read on another page: a fare found on the way, typed into a document.
        ctx = replace(ctx, earlier=earlier_screens(state, state.last))
    allowed = permitted(cfg, ctx, state, screen, items, decision, log)
    if allowed is None:
        return False
    ctx = allowed
    with phase(timing, "act"):
        what = perform(decision, screen, items, ctx)
    state.view = None
    if state.guidance.focus and decision.kind.choice != "wait" and "refused:" not in what:
        state.guidance = state.guidance.followed()
        log("  the focus is followed; back to the goal")
    state.clicked = clicked_field(screen, items, decision, what)
    state.pending_click = click_taken(screen, items, decision, what)
    state.history.append(what)
    log(f"  did: {what}")
    log.event("action", text=what, actions=len(state.history))
    return not repeating(state, what, decision.kind.choice == "wait", log, decision.kind.choice in NAVIGATIONS)


def permitted(
    cfg: RunConfig, ctx: Context, state: RunState, screen: Screen, items: list[Item], decision: Decision, log: Log
) -> Context | None:
    """The context to take this action with, under the run's permissions; None when it may not be taken,
    with the outcome set.

    With `full` every action goes, as it always did. Otherwise each click, key and typing is first put
    to the decision model as an action alone: would it change something? One that would is never taken
    under `look`, and under `ask` waits for the user's yes. A run nobody can ask is a run that may
    only look. Unsure, or no answer, holds the action: a wrong hold costs a handoff, a wrong click on
    "Place order" costs money. The read-only gate does not stand in for this: it asks about the goal,
    and a goal that only checks stock was still one click from "Add to Bag".

    Typing is written before it is asked about, so the question shows the words that would go in, and
    the context returned carries them, so the same words are typed.
    """
    kind = decision.kind.choice
    if cfg.permissions == "full" or kind not in GUARDED_KINDS:
        return ctx
    if kind == "type_text":
        ctx = replace(ctx, fill=prewritten(ctx, screen, items))
        if ctx.fill is not None and not ctx.fill.text:
            return ctx  # the writer declined: nothing would be typed, and the action refuses itself
    held = HeldAction.of(decision, screen, items, ctx.fill)
    key = click_key(screen.app, screen.url, held.what)
    if key in state.allowed:
        return ctx
    item = next((it for it in items if decision.item is not None and str(it.index) == decision.item.choice), None)
    beside = row_mates(items).get(item.index) if item is not None and (decision.clicking or decision.pointing) else None
    try:
        p = changes_something(ctx.typesafe, cfg.goal, screen, held.what, beside)
    except DecisionError as e:
        log(f"  could not tell whether {held.what} changes something ({e}), so it is held")
        p = 1.0
    if p < CHANGES_NOUL:
        return ctx
    record = {"step_action": len(state.history) + 1, "action": held.what, "changes": round(p, 3), "permissions": cfg.permissions}
    state.held.append(record)
    if cfg.permissions == "look" or ctx.ask is None:
        why = "this run may only look" if cfg.permissions == "look" else "nobody is there to allow it"
        log(f"  {held.what} would change something ({p:.2f}) and {why}; stopping")
        record["result"] = "held"
        state.outcome = "look only"
        return None
    question = f"May I {held.what}? It would change something. Reply yes to go ahead."
    log(f"  {held.what} would change something ({p:.2f}); asking")
    # What the menu bar app draws its card from; the question that follows is what it answers.
    log.event("permission", kind=held.kind, title=held.title, text=held.text, where=held.where, question=question)
    reply = ctx.ask(question).strip()
    record["reply"] = reply
    log(f"  > {reply}", echo=False)
    if cfg.act and not cfg.replay:
        desktop.activate(screen.app)  # answering may have taken another app to the front; put the work back there
    if said_yes(reply):
        log("  allowed")
        record["result"] = "allowed"
        state.allowed.add(key)
        return ctx
    log("  not allowed; stopping")
    record["result"] = "declined"
    if reply:  # a "no, open the reviews instead" is something for the writer to go on
        state.guidance = state.guidance.heard(question, reply)
    state.outcome = "declined"
    return None


def prewritten(ctx: Context, screen: Screen, items: list[Item]) -> Fill | None:
    """The text a type_text would put in the focused field, written now; None when it cannot be, and
    the action is left to refuse itself as it would have."""
    if ctx.writer is None or not (screen.field and screen.field.is_text):
        return None
    try:
        return compose_text(ctx.writer, ctx.goal, screen, items, ctx.history, ctx.guidance, ctx.earlier)
    except WriterError:
        return None


@dataclass(frozen=True)
class HeldAction:
    """An action the permissions put to the user, in the words the log, the question and the app's card use."""

    kind: str  # type, click, key, drag or shortcut: what the app draws its icon from
    what: str  # the action in a phrase: "type 'see you at 6' into Message"
    title: str  # the card's line: "Type into Message"
    text: str | None  # the words that would be typed, shown under the title
    where: str  # the app, and the page without its query: "Brave Browser · instagram.com/direct"

    @staticmethod
    def of(decision: Decision, screen: Screen, items: list[Item], fill: Fill | None) -> HeldAction:
        kind = decision.kind.choice
        into = field_name(screen.field) if screen.field is not None else "the focused field"
        text = fill.text if fill is not None and fill.text else None
        if kind == "type_text":
            what = f"type {text!r} into {into}" if text else f"type into {into}"
            held = ("type", what, f"Type into {into}")
        elif kind == "type_email":
            held = ("type", f"type your email into {into}", f"Type your email into {into}")
        elif kind == "press_enter":
            held = ("key", f"press Return in {into}", f"Press Return in {into}")
        else:
            what = intended(decision, screen, items)
            sort = "drag" if decision.dragging else "shortcut" if decision.pressing_shortcut else "click"
            held = (sort, what, what[:1].upper() + what[1:])
        return HeldAction(*held, text=text if kind == "type_text" else None, where=place(screen))


def field_name(f: Field) -> str:
    """What a field is called on screen: its label, else its placeholder, else its role in words
    ("the text area"), never the raw accessibility role."""
    named = (f.label or f.placeholder or "").strip()
    if named:
        return named
    role = re.sub(r"(?<!^)(?=[A-Z])", " ", f.role.removeprefix("AX")).lower().strip()
    return f"the {role or 'focused field'}"


def place(screen: Screen) -> str:
    """The app, and the page without its query or fragment, for the user to tell where an action is."""
    if not screen.url:
        return screen.app
    parts = urlparse(screen.url)
    page = (parts.netloc.removeprefix("www.") + parts.path).rstrip("/")
    return f"{screen.app} · {page[:60]}" if page else screen.app


def said_yes(reply: str) -> bool:
    """A yes as people type it: "yes", "Yes please", "ok, go ahead", "go ahead". Anything else is a no."""
    words = re.sub(r"[^\w\s]", " ", reply.lower()).split()
    return bool(words) and (words[0] in YES or " ".join(words[:2]) in YES)


def click_key(app: str, url: str | None, text: str) -> tuple:
    """What identifies a clicked item from one visit of its page to the next: the app, the page without its
    query or fragment, and the item's words."""
    page = url.split("#")[0].split("?")[0] if url else None
    return (app, page, " ".join(text.lower().split()))


def click_taken(screen: Screen, items: list[Item], decision: Decision, what: str) -> tuple | None:
    """The click just made, for the next capture to say what it did: its key, and the screen it was made on."""
    if not (decision.clicking or decision.pointing) or REFUSED.match(what):
        return None
    item = next((it for it in items if str(it.index) == decision.item.choice), None)
    if item is None:
        return None
    return click_key(screen.app, screen.url, item.text), screen.app, screen.url, signature(screen, items)


def remember_clicks(state: RunState, screen: Screen, items: list[Item]) -> None:
    """Say what the last click did, now that its screen is captured, and mark each item on this screen
    that was clicked before with what that did.

    The classifier remembers nothing past the last eight actions, and the repeat rule counts an action
    only on the same screen. On a messages inbox whose "active 2m ago" lines change by the minute, no
    two captures were the same screen: asked to go through the conversations, the run opened the same
    two again and again, and kept clicking a name in a strip of status notes that only opened a popover.
    What a click did is a fact the code sees, so it goes on the item.
    """
    if state.pending_click is not None:
        key, app, url, before = state.pending_click
        state.pending_click = None
        if screen.app != app:
            did = f"opened {screen.app}"
        elif screen.url != url and screen.url:
            did = f"opened {screen.url}"
        elif same_screen(before, signature(screen, items)):
            did = "changed nothing"
        else:
            did = "changed this page without leaving it, such as opening a popover"
        state.clicks[key] = did
    screen.clicked_before.clear()
    screen.clicked_before.update(
        {it.index: state.clicks[key] for it in items if (key := click_key(screen.app, screen.url, it.text)) in state.clicks}
    )


def named_by_focus(decision: Decision, items: list[Item], focus: str | None) -> str | None:
    """The text of the item the classifier would click, when the writer's focus quotes it, else None.

    A decision model that spreads an item's odds over every item on screen gives the right one
    0.2 and stops short of it; the writer, reading the same screen, named it in its focus. Two
    models agreeing on one item is the confidence the floor stands for. The quote must name
    that item and not its twin: a Firebase page shows a "Manage →" on two cards, so the one
    clicked must be FOCUS_LEAD times likelier than any other item of the same text.
    """
    if not focus or not decision.clicking:
        return None
    by_index = {str(it.index): it for it in items}
    top = by_index.get(decision.item.choice)
    quotes = {_bare(next(g for g in m.groups() if g)) for m in QUOTED.finditer(focus)}
    if top is None or _bare(top.text) not in quotes:
        return None
    twins = [key for key, it in by_index.items() if key != decision.item.choice and _bare(it.text) == _bare(top.text)]
    rival = max((decision.item.probabilities.get(key, 0.0) for key in twins), default=0.0)
    return top.text if decision.item.confidence >= FOCUS_LEAD * rival else None


def _bare(text: str) -> str:
    """Text as a focus quotes it: no arrow, icon, or punctuation at either end, and no case."""
    return re.sub(r"^\W+|\W+$", "", text).casefold()


def keys_desc(screen: Screen) -> str:
    """Where the keyboard goes, for the step line, when it is not the app in front: it says why a
    screen with no focused field cannot be typed into."""
    keys = screen.keys
    if keys is None:
        return ""
    nobody = "no app" + (f" ({keys.error})" if keys.error else "")
    return f" keys={keys.app or nobody!r}" if keys.app != screen.app else ""


def clicked_field(screen: Screen, items: list[Item], decision: Decision, what: str) -> Clicked | None:
    """Where a click on text read off the page landed, kept to stand in for the field it may have focused.

    Only a mouse click on page text counts: a control from the accessibility tree is reported with
    its focus when it takes it, and the menu bar is no page.
    """
    if not decision.clicking or "click refused" in what:
        return None
    item = next((it for it in items if str(it.index) == decision.item.choice), None)
    if item is None or item.from_ax or screen.in_menu_bar(item):
        return None
    s = screen.scale
    box = Field(
        role="",
        label=item.text,
        placeholder="",
        value="",
        x=item.x1 / s,
        y=item.y1 / s,
        w=(item.x2 - item.x1) / s,
        h=(item.y2 - item.y1) / s,
        clicked=True,
    )
    return screen.app, screen.url, box


def with_clicked_field(screen: Screen, clicked: Clicked | None, browsers: list[str]) -> Screen:
    """The screen, with the box the last click landed in as its focused field when a browser reports none.

    Chromium browsers keep their pages out of accessibility, and then report no focused element at
    all, so a click into a text box reads as a click on nothing. type_text is never offered, and the
    run clicks the box until it stalls. Only the screen right after the click gets the stand-in, in
    the same browser on the same page; the classifier is told it may not be a text box.
    """
    if screen.field is not None or clicked is None or screen.app not in browsers:
        return screen
    app, url, box = clicked
    if (screen.app, screen.url) != (app, url):
        return screen
    return replace(screen, field=box)


POINTING_WORDS = {
    "right_click_item": "right-click",
    "double_click_item": "double-click",
    "select_item_text": "select the text of",
}


def intended(decision: Decision, screen: Screen, items: list[Item]) -> str:
    """What a dry run would have done, in words: a click names the text it would land on, not its index."""
    if decision.clicking:
        item = next((it for it in items if str(it.index) == decision.item.choice), None)
        return f"click {item.text!r}" if item is not None else decision.chosen
    if decision.dragging:
        named = {str(it.index): it.text for it in items}
        return f"drag {named.get(decision.item.choice)!r} onto {named.get(decision.target.choice)!r}"
    if decision.pointing:
        item = next((it for it in items if str(it.index) == decision.item.choice), None)
        return f"{POINTING_WORDS[decision.kind.choice]} {item.text!r}" if item is not None else decision.chosen
    if decision.pressing_offscreen:
        return f"press {screen.offscreen[int(decision.offscreen.choice)].label!r}"
    if decision.pressing_shortcut:
        return f"press the {decision.shortcut.choice.replace('_', ' ')} shortcut"
    return decision.kind.choice.replace("_", " ")


def screen_moved(state: RunState, screen: Screen, items: list[Item], log: Log) -> bool:
    """Count the actions that left the screen as it was, and stop once too many did in a row.

    The capture is the only witness to what an action did. Compared with the one the action was
    taken on, an unchanged screen means a refused action, a wait on a page still loading, or a
    scroll that has run out of page; any of them is fine a couple of times. A page the run has not
    been on before starts the count of stalls again (see `stuck`).
    """
    now = signature(screen, items)
    if now[:2] not in state.pages:
        state.pages.add(now[:2])
        state.stalls = 0
    if state.last is not None:
        state.idle = state.idle + 1 if same_screen(now, state.last) else 0
    state.last = now
    if state.idle >= MAX_IDLE:
        log(f"  the last {MAX_IDLE} actions changed nothing on screen; stopping")
        state.outcome = "stalled"
        return False
    return True


def tried_here(state: RunState) -> list[str]:
    """The actions already taken on the screen now showing, oldest first, for the classifier to steer around."""
    return [what for seen, what in state.seen if what is not None and state.last is not None and same_screen(seen, state.last)]


def repeating(state: RunState, what: str, waiting: bool, log: Log, navigating: bool = False) -> bool:
    """Count the actions already taken on the same screen earlier, and stop once too many run in a row.

    The same action on the same screen led somewhere once, and this is where it led: back here.
    That is a cycle through two pages as much as a button that does nothing. A wait is recorded
    with no action, so the screen it was taken on still reaches the answer, but it is never a
    repeat and never listed as tried: waiting is repeating by design, and the classifier must
    stay free to wait again. The idle count bounds it instead.

    A navigation is judged by where it went, not by the screen it was taken on. A site that answers
    with an error page reads a line differently each time, so a run that opened it again and again
    never took the same action on the same screen twice, and nothing stopped it. The place is a
    fact the history line holds, and opening what the last action just opened gains nothing.
    """
    if waiting:
        state.seen.append((state.last, None))
        return False
    state.repeats = state.repeats + 1 if what in tried_here(state) else 0
    state.revisits = state.revisits + 1 if navigating and what == state.navigated else 0
    state.navigated = what if navigating else None
    state.seen.append((state.last, what))
    if state.repeats >= MAX_REPEATS:
        log(f"  {MAX_REPEATS} actions in a row already taken on the same screen; stopping")
        state.outcome = "stalled"
        return True
    if state.revisits >= MAX_REVISITS:
        log(f"  {what!r} {MAX_REVISITS + 1} times in a row; stopping")
        state.outcome = "stalled"
        return True
    return False


def answers(
    decision: Decision, screen: Screen, items: list[Item], timing: dict[str, float], tried: list[str], state: RunState
) -> dict:
    """What the classifier returned for this step, plus what it cost and where the stop rules stand."""
    return {
        "kind": decision.kind.choice,
        "kind_confidence": decision.kind.confidence,
        "kind_probabilities": decision.kind.probabilities,
        "refused": decision.refused,
        "item": decision.item.choice if decision.item else None,
        "item_confidence": decision.item.confidence if decision.item else None,
        "item_probabilities": decision.item.probabilities if decision.item else None,
        "site": decision.site.choice,
        "site_probabilities": decision.site.probabilities,
        **(
            {"browser": decision.browser.choice, "browser_probabilities": decision.browser.probabilities}
            if decision.browser
            else {}
        ),
        **({"app_to_open": decision.app.choice, "app_to_open_probabilities": decision.app.probabilities} if decision.app else {}),
        **(
            {"shortcut": decision.shortcut.choice, "shortcut_probabilities": decision.shortcut.probabilities}
            if decision.shortcut
            else {}
        ),
        **({"target": decision.target.choice, "target_probabilities": decision.target.probabilities} if decision.target else {}),
        "offscreen": decision.offscreen.choice if decision.offscreen else None,
        "offscreen_probabilities": decision.offscreen.probabilities if decision.offscreen else None,
        "offscreen_controls": offscreen_records(screen.offscreen),
        "chosen": decision.chosen,
        "confidence": decision.confidence,
        "already_tried_on_this_screen": tried,
        "idle_actions": state.idle,
        "repeated_actions": state.repeats,
        "timing": timing,
        "items": [asdict(it) for it in items],
        "field": screen.field.record() if screen.field else None,
        "keyboard": asdict(screen.keys) if screen.keys else None,
        "app": screen.app,
        "url": screen.url,
    }

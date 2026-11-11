"""The classifier side: state, criteria, and the one multi-Choice request."""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from .config import SHORTCUTS, SITES
from .dates import date_hints, now_context
from .decisions import Choice, ChoiceAnswer, DecisionClient, DecisionError, Noul, Refusal
from .models import AxNode, Field, Guidance, Item, Screen

STOP_KINDS = ("done", "none")
SHORTCUT_KIND = (
    "Press a keyboard shortcut from a short list: the shortcut question that follows says which. "
    "Use it for a command the goal needs that no control on screen does, or that the keys do "
    "in one step: copy or paste a selection, select all, undo, find on the page, switch tabs. "
    "Not for Return, Escape, or going back, which have actions of their own, not to open a website "
    "(use_browser does that), and not when a button on screen does the same thing."
)
# What the goal question lists, so that it opens for the moves the run is offered and no others.
MOVES_ASKED = (
    "a keyboard shortcut or a named key (copy, paste, select all, undo, find on the page, switch or reopen tabs, "
    "Tab between fields), the context menu of an item (a right click), a double click, selecting the text of an "
    "item, or dragging one item onto another"
)
OFFSCREEN_PREFIX = "offscreen:"
# The questions a step is asked again without when the model refuses one, each with the one kind
# of action that cannot go ahead without its answer.
# The kinds of click other than a single one, each acting on the item the item question picks.
POINTING = {
    "right_click_item": (
        "Open the context menu of one of the on-screen items (chosen in the item question). Use only when the "
        "goal needs an option that only a context menu offers, such as opening a link in a new tab or copying "
        "a link. The menu's entries are on screen at the next step."
    ),
    "double_click_item": (
        "Double-click one of the on-screen items (chosen in the item question): to open a file or folder in a "
        "list that opens its items by double-click. Not for a link, a button, a checkbox, or anything that one "
        "click already activates."
    ),
    "select_item_text": (
        "Select the whole line or paragraph of an on-screen text item with a triple click (chosen in the item "
        "question), so that it can be copied. Use when the goal needs that text copied and no control on screen "
        "selects it. Not when the focused field already shows that text as selected. Typing afterwards does not "
        "act on the selection."
    ),
}
DRAG = (
    "Drag one on-screen item (chosen in the item question) onto another (chosen in the target question that "
    "follows): to move a file into a folder, reorder a list or the tabs, or drop something on a place. Not "
    "for a slider or a map, and not when a menu or a button on screen does the same."
)
SPARED = {"item": ("click_item", *POINTING, "drag_item"), "offscreen": ("press_offscreen",)}
GATED_KINDS = frozenset({"press_shortcut", *POINTING, "drag_item"})  # offered only to a run whose goal needs the moves
PRESS_OFFSCREEN = (
    "Activate a labelled control that the app exposes but that is not currently visible on screen "
    "(chosen in the offscreen question). Use when the needed control is known to exist but is "
    "scrolled out of view or not yet shown."
)

# Said only while a focus is set, so a run the writer never steered asks the question it always asked.
FOCUS_RULE = (
    " The current focus is the next step on the way to the goal, set by a reviewer that read the "
    "screen when you last stopped: work toward it. 'done' still means the goal itself, not the focus."
)


def fixed_actions(
    browser: str, email: str | None, browsers: Sequence[str] = (), apps: Sequence[str] = (), moves: bool = False
) -> dict[str, str]:
    """Deterministic actions offered alongside click_item. Keep them mutually exclusive.

    `moves` offers the moves beyond clicking and typing, for a run whose goal needs them (see `needs_moves`)."""
    where = "a web browser (the browser question says which)" if len(browser_names(browser, browsers)) > 1 else browser
    actions = {
        "use_browser": (
            f"Work in {where}: bring it to the front, and open a website there if one is needed. The "
            "site question says which website, or says that the page already open there is the one to "
            "continue with. This is the only way to reach a website: never click the address bar, a URL, "
            "or a search box to get there. Works from any app, including this one."
        ),
        **(
            {
                "open_app": (
                    "Open an app installed on this computer, or bring it to the front when it is already "
                    "open: the app question that follows says which. This is the only way to reach an app "
                    "that is not in front. Not for a website or a web browser: use_browser does those."
                )
            }
            if apps
            else {}
        ),
        "type_text": (
            "Type free text into the focused text field. A writing model composes the text from the "
            "goal and the field's label. Only valid when a text field is focused and needs content. "
            "Where the browser hides its focus, the focused field is the item the last click landed "
            "on: valid when that item is a text box."
        ),
        "press_enter": "Press Return to submit the focused form or field.",
        "press_escape": "Press Escape to dismiss a dialog, menu, or popup.",
        "go_back": (
            "Go back to the previous page or screen, as the browser's Back button does. Use when the last "
            "click led somewhere that does not help and the page before it did."
        ),
        "scroll_down": (
            "Scroll down to reveal more of the page, or of the list or panel the goal needs more of. "
            "The scroll goes to the item the item question picks, so a list beside a map scrolls and "
            "the map stays still."
        ),
        "scroll_up": "Scroll up, over the item the item question picks.",
        "wait": "Nothing to do yet; the screen is still loading or changing.",
        "done": "The goal is already achieved.",
        "none": "Nothing on screen or in this list helps with the goal.",
    }
    if moves:
        actions = {**actions, "press_shortcut": SHORTCUT_KIND}
    if email:
        actions["type_email"] = (
            "Type the user's email address into the focused text field. Use this, not type_text, "
            "whenever the field wants an email or username."
        )
    return actions


def kind_criteria(
    browser: str,
    email: str | None,
    offscreen: bool = False,
    browsers: Sequence[str] = (),
    apps: Sequence[str] = (),
    moves: bool = False,
    draggable: bool = True,
) -> dict[str, str]:
    """`draggable` is whether two items are on screen: a drag needs one to take and another to drop it on."""
    clicks = {
        "click_item": "Click one of the on-screen text items (chosen in the item question).",
        **({**POINTING, **({"drag_item": DRAG} if draggable else {})} if moves else {}),
    }
    if offscreen:
        clicks["press_offscreen"] = PRESS_OFFSCREEN
    return {**clicks, **fixed_actions(browser, email, browsers, apps, moves)}


ROW_MATES = 3  # how many neighbours name a duplicated item's row in the state; the history line takes more
HISTORY_MATES = 8  # the longest row a history line names whole; a longer one (a strip of tabs, a toolbar) is cut
HISTORY_SHOWN = 3  # to this many of its items, a count of the rest, and a tag that stands for the whole row


def beside(mates: list[str]) -> str:
    """The row, as a history line names it. The whole row while it is HISTORY_MATES items or fewer, so that two
    rows that open alike get lines of their own. A longer one tells its items apart no better and was sent with
    every request after it (33 tab titles in one line steered the shortcut question to close_tab, on a goal that
    had already closed the tab, at 0.38 to 0.46), so it is cut to its first items and a count, and a short tag of
    the whole row keeps two long rows that open alike, each with a Delete, from reading as the same action to
    the repeat rule."""
    if len(mates) <= HISTORY_MATES:
        return ", ".join(repr(m) for m in mates)
    tag = hashlib.blake2s("\x1f".join(mates).encode(), digest_size=2).hexdigest()
    return ", ".join(repr(m) for m in mates[:HISTORY_SHOWN]) + f" and {len(mates) - HISTORY_SHOWN} more (row {tag})"


def row_mates(items: list[Item], limit: int | None = ROW_MATES) -> dict[int, list[str]]:
    """Item index -> the texts sharing its row, left to right, for every item whose text another item repeats.

    Three rows of events each end in a 'Buy'. The label says nothing about which; the row does,
    and the row is a fact the layout holds, so the code reads it and hands it over. `limit`
    keeps a criterion short; None takes the whole row, for a line that has to identify it.
    """
    counts = Counter(it.text for it in items)
    out: dict[int, list[str]] = {}
    for it in items:
        if counts[it.text] < 2:
            continue
        cy, half = it.center[1], max(1.0, it.y2 - it.y1) / 2
        mates = sorted((o for o in items if o is not it and abs(o.center[1] - cy) < half), key=lambda o: o.x1)
        if mates:
            out[it.index] = [o.text for o in mates[:limit]]
    return out


def item_criteria(screen: Screen, items: list[Item]) -> dict[str, str]:
    """Each item as a pointer to its row in the state's list, which holds what there is to know of it: its
    text, where it sits, the role the app declared, a date, the row it shares, a popup over it.

    The criterion used to repeat all of that, so every item went out twice, and together the two copies
    were 85% of a request. The list in the state cannot go (without it the kind question loses the screen:
    silver agreement 0.60 to 0.45 on saved steps, scrolling picked twice as often); the criterion can. With
    a pointer, a request is 26% smaller and its input tokens 17%, and the same items are picked."""
    return {str(it.index): f"Item {it.index}." for it in items}


def offscreen_criteria(nodes: list[AxNode]) -> dict[str, str]:
    """Each off-screen control as one line, keyed by its position in `screen.offscreen`."""
    return {str(i): f"{node.role_word} {node.label!r} (not visible)" for i, node in enumerate(nodes)}


def offscreen_records(nodes: list[AxNode]) -> list[dict]:
    """The same controls as state, with the key the offscreen question answers with."""
    return [{"k": i, "role": node.role_word, "label": node.label} for i, node in enumerate(nodes)]


def site_criteria() -> dict[str, str]:
    """Which website use_browser opens. The catalog, plus one key for anything else and one for nothing."""
    return {
        **SITES,
        "other": "A website is needed to progress the goal, but it is not one of the sites named in this list.",
        "none": "No website needs to be opened: the page already open in the browser is the one to continue with.",
    }


def browser_names(browser: str, browsers: Sequence[str]) -> list[str]:
    """The browsers use_browser can work in: the configured one first, then the other installed ones."""
    return [browser, *(name for name in browsers if name != browser)]


def browser_criteria(browser: str, browsers: Sequence[str], frontmost: str) -> dict[str, str]:
    """Each browser as one line, with the two facts the code knows about it: which one is in front
    now and which one is the default. Whether the goal asks for one is the classifier's call."""

    def line(name: str) -> str:
        facts = [fact for fact, true in (("the app in front now", name == frontmost), ("the default", name == browser)) if true]
        return f"Work in {name}" + (f" ({'; '.join(facts)})." if facts else ".")

    return {name: line(name) for name in browser_names(browser, browsers)}


def app_criteria(apps: Sequence[str], frontmost: str) -> dict[str, str]:
    """Which app open_app opens. Each installed app, the one in front marked, plus one key for none of them."""
    return {
        **{name: f"Open {name}" + (" (the app in front now)." if name == frontmost else ".") for name in apps},
        "none": "None of these apps is the one the goal needs.",
    }


def shortcut_criteria() -> dict[str, str]:
    """Which shortcut press_shortcut presses. The catalog, plus one key for none of them."""
    return {
        **{name: shortcut.says for name, shortcut in SHORTCUTS.items()},
        "none": "None of these shortcuts is what the goal needs.",
    }


def base_state(
    goal: str,
    screen: Screen,
    items: list[Item],
    history: list[str],
    tried: list[str] | None = None,
    guidance: Guidance | None = None,
    moves: bool = False,
) -> dict:
    """The facts the classifier reads. `tried` lists the actions already taken on this same screen
    earlier in the run, each of which led back here: a fact the code knows and the model cannot.
    `guidance` is what the writer and the user added to the goal when the classifier last stopped.
    `moves` is whether the run is offered the moves beyond clicking and typing: then the field says what
    text is selected in it, which a selection leaves no other trace of."""
    hints = date_hints(items, screen)
    mates = row_mates(items)
    return {
        "goal": goal,
        **(guidance.state() if guidance else {}),
        "now": now_context(),
        "frontmost_app": screen.app,
        "browser_active_tab_url": screen.url,
        "focused_field": screen.field.summary(selection=moves) if screen.field else None,
        "previous_actions": history[-8:],
        "already_tried_on_this_screen": list(tried or []),
        "screen_items_in_reading_order": [
            {
                "i": it.index,
                "text": it.text,
                "where": screen.region(it),
                **({"role": it.role} if it.role else {}),
                **({"when": hints[it.index]} if it.index in hints else {}),
                **({"beside": mates[it.index]} if it.index in mates else {}),
                **({"under": screen.covered[it.index].title} if it.index in screen.covered else {}),
            }
            for it in items
        ],
        **({"offscreen_controls": offscreen_records(screen.offscreen)} if screen.offscreen else {}),
    }


@dataclass(frozen=True)
class Decision:
    kind: ChoiceAnswer
    item: ChoiceAnswer | None
    site: ChoiceAnswer
    offscreen: ChoiceAnswer | None = None
    browser: ChoiceAnswer | None = None  # asked only when more than one browser is installed
    app: ChoiceAnswer | None = None  # asked only once open_app is chosen
    shortcut: ChoiceAnswer | None = None  # asked only once press_shortcut is chosen
    target: ChoiceAnswer | None = None  # asked only once drag_item is chosen: the item the dragged one is dropped on
    refused: str | None = None  # a question the model refused, so the step was decided without it

    @property
    def clicking(self) -> bool:
        return self.kind.choice == "click_item" and self.item is not None

    @property
    def pointing(self) -> bool:
        """A click of another kind than a single one, on the item the item question picked."""
        return self.kind.choice in POINTING and self.item is not None

    @property
    def dragging(self) -> bool:
        return self.kind.choice == "drag_item" and self.item is not None and self.target is not None

    @property
    def pressing_offscreen(self) -> bool:
        return self.kind.choice == "press_offscreen" and self.offscreen is not None

    @property
    def pressing_shortcut(self) -> bool:
        return self.kind.choice == "press_shortcut" and self.shortcut is not None

    @property
    def chosen(self) -> str:
        if self.clicking:
            return self.item.choice
        if self.pressing_offscreen:
            return f"{OFFSCREEN_PREFIX}{self.offscreen.choice}"
        return self.kind.choice

    @property
    def confidence(self) -> float:
        # Only the answers that name a target lower the confidence: a click or a press lands
        # somewhere, and the wrong somewhere is not undone. use_browser reads the site and browser
        # answers too, and open_app the app answer, but every outcome of them is a page or an app
        # the next step can leave, so a split there must not stop the run.
        if self.clicking or self.pointing:
            return min(self.kind.confidence, self.item.confidence)
        if self.pressing_offscreen:
            return min(self.kind.confidence, self.offscreen.confidence)
        if self.dragging:
            return min(self.kind.confidence, self.item.confidence, self.target.confidence)  # a drag moves things
        if self.pressing_shortcut:
            return min(self.kind.confidence, self.shortcut.confidence)  # a wrong shortcut is not always undone
        return self.kind.confidence

    @property
    def stops(self) -> bool:
        return self.kind.choice in STOP_KINDS


def build_questions(
    screen: Screen,
    items: list[Item],
    browser: str,
    email: str | None,
    guidance: Guidance | None = None,
    browsers: Sequence[str] = (),
    apps: Sequence[str] = (),
    moves: bool = False,
) -> dict[str, Choice]:
    """The questions one step asks, apart from the app question, which a request of its own follows
    only once open_app is chosen. `decide` sends them, and the eval kit builds them the same way to
    measure a request without sending it."""
    questions = {
        "kind": Choice(
            instructions=(
                "You are driving this computer one action at a time. Which kind of action "
                "makes the most progress toward the goal right now? Do not repeat an action "
                "that was just taken unless the screen changed, and never one listed as already "
                "tried on this screen: each of those led straight back here."
                + (FOCUS_RULE if guidance and guidance.focus else "")
            ),
            criteria=kind_criteria(browser, email, bool(screen.offscreen), browsers, apps, moves, len(items) >= 2),
        ),
        "site": Choice(
            instructions=(
                "If the browser is used this step, which website should it show? Name a site from the "
                "list when the goal calls for that one, 'other' when the goal calls for a site the list "
                "does not name, and 'none' to stay on the page that is already open in the browser."
            ),
            criteria=site_criteria(),
        ),
    }
    if len(browser_names(browser, browsers)) > 1:
        questions["browser"] = Choice(
            instructions=(
                "If the browser is used this step, which browser? The one the goal names; when it names "
                "none, the one in front now if it is a browser, and the default otherwise."
            ),
            criteria=browser_criteria(browser, browsers, screen.app),
        )
    if items:
        questions["item"] = Choice(
            instructions=(
                "If clicking an on-screen item is the right move,"
                + (
                    " by any click (single, right, double, or the triple click that selects its text), or, for a drag,"
                    " the item that is dragged,"
                    if moves
                    else ""
                )
                + " which item? If scrolling is, which "
                "item sits in the list, panel, or page that should scroll? Pick a line of that content "
                "itself, not a sidebar or menu entry that shares a word with the goal: the wheel turns "
                "whatever is under the pointer, so over a sidebar link the sidebar scrolls, or its "
                "menu opens, and the page stays where it was. Items marked with a "
                "role come from the app's accessibility tree and are real controls; plain items are "
                "text read from the screen. Never pick an item that an action listed as already tried "
                "on this screen clicked or pressed: each of those led straight back here."
            ),
            criteria=item_criteria(screen, items),
        )
    if screen.offscreen:
        questions["offscreen"] = Choice(
            instructions=(
                "If activating a control that is not on screen is the right move, which control? "
                "These are real controls of the app, reachable without the mouse, but nothing on "
                "the capture points at them."
            ),
            criteria=offscreen_criteria(screen.offscreen),
        )
    return questions


def decide(
    client: DecisionClient,
    goal: str,
    screen: Screen,
    items: list[Item],
    history: list[str],
    browser: str,
    email: str | None,
    tried: list[str] | None = None,
    guidance: Guidance | None = None,
    browsers: Sequence[str] = (),
    apps: Sequence[str] = (),
    moves: bool = False,
) -> Decision:
    """One request for the step's decision, and a second, small one for the app only when the first
    chose open_app: the list of installed apps is long, and most steps open none. A shortcut is asked
    the same way, once press_shortcut is chosen, and so is the item a drag drops on.

    Luna refused the item question now and then when its labels were the text read off the screen, and
    OpenRouter loses every other answer with it: on a Claude window full of a conversation about IAM roles,
    a run never got as far as opening the browser the goal named. Most moves need no item, so the step is
    asked again without it, and only a click is left without a decision. It refuses the off-screen question
    the same way, and only pressing one of those controls needs it. The item labels are pointers to the
    state's rows now (`Item N.`) and the screen text sits in the state, so whether Luna still refuses this
    question has not been measured; the fallback stays until it has.
    """
    questions = build_questions(screen, items, browser, email, guidance, browsers, apps, moves)
    state = base_state(goal, screen, items, history, tried, guidance, moves)
    refused = None
    try:
        answers = client.system_one(state=state, questions=questions).answers
    except Refusal as e:
        if e.question not in SPARED or e.question not in questions:
            raise
        refused = e.question
        rest = {name: question for name, question in questions.items() if name != refused}
        answers = client.system_one(state=state, questions=rest).answers
        if answers["kind"].choice in SPARED[refused]:
            raise DecisionError(f"the model refused {refused!r}, then chose {answers['kind'].choice} without it ({e})") from e
    app = None
    if answers["kind"].choice == "open_app" and apps:
        app = client.system_one(
            state={"goal": goal, **(guidance.state() if guidance else {}), "frontmost_app": screen.app},
            questions={"app": app_question(apps, screen.app)},
        ).answers["app"]
    shortcut = None
    if answers["kind"].choice == "press_shortcut":
        shortcut = client.system_one(
            state={
                "goal": goal,
                **(guidance.state() if guidance else {}),
                "frontmost_app": screen.app,
                "focused_field": screen.field.summary(selection=True) if screen.field else None,
                "previous_actions": history[-8:],
            },
            questions={"shortcut": shortcut_question()},
        ).answers["shortcut"]
    target = None
    # A source under a popup is refused by the action whatever the target, and with nothing to drop it on the
    # question would have no choices: neither is worth a request.
    if (
        answers["kind"].choice == "drag_item"
        and answers.get("item") is not None
        and not covered(screen, answers["item"].choice)
        and target_question(screen, items, answers["item"].choice).criteria
    ):
        source = answers["item"].choice
        target = client.system_one(
            state={
                "goal": goal,
                **(guidance.state() if guidance else {}),
                "frontmost_app": screen.app,
                "dragging_item": source,
                "screen_items_in_reading_order": state["screen_items_in_reading_order"],
            },
            questions={"target": target_question(screen, items, source)},
        ).answers["target"]
    return Decision(
        kind=answers["kind"],
        item=answers.get("item"),
        site=answers["site"],
        offscreen=answers.get("offscreen"),
        browser=answers.get("browser"),
        app=app,
        shortcut=shortcut,
        target=target,
        refused=refused,
    )


def app_question(apps: Sequence[str], frontmost: str) -> Choice:
    return Choice(
        instructions=(
            "An app is to be opened this step. Which app does the goal, or the current focus, need? The "
            "one it names; when it names none, the one made for the task it describes."
        ),
        criteria=app_criteria(apps, frontmost),
    )


def covered(screen: Screen, key: str) -> bool:
    """Whether a popup is in front of the item with this key: the action refuses to press or drop there."""
    return key.isdigit() and int(key) in screen.covered


def target_question(screen: Screen, items: list[Item], source: str) -> Choice:
    """Which item the dragged one is dropped on: every item but the dragged one, and none under a popup,
    in the item question's words."""
    return Choice(
        instructions=(
            "An on-screen item is dragged this step (the state's dragging_item). Which item is it dropped "
            "on? The one the goal, or the current focus, moves it to: a folder, a slot in a list, a tab."
        ),
        criteria={key: line for key, line in item_criteria(screen, items).items() if key != source and not covered(screen, key)},
    )


def shortcut_question() -> Choice:
    return Choice(
        instructions=(
            "A keyboard shortcut is to be pressed this step. Which one does the goal, or the current "
            "focus, need? The one that does what it describes; 'none' when no shortcut in the list does. "
            "A goal can take several in turn, such as select all, then copy, then paste: choose the next one "
            "that is still to be pressed, going by the previous actions and by what is selected in the focused "
            "field, and never one whose effect is already there."
        ),
        criteria=shortcut_criteria(),
    )


def needs_moves(client: DecisionClient, goal: str) -> float:
    """Probability that the goal needs a move beyond clicking and typing: a shortcut, and the like.

    Asked once a run, of the goal alone, as `read_only` is. The moves sit in the kind question only
    for a run that needs them: offered on every step, a new kind pulled the classifier off picks it
    had right on steps that needed none of them, by 2.6 points of agreement on saved steps.
    """
    question = Noul(
        instructions=(
            "Does reaching this goal need a move that clicking links and buttons and typing into fields cannot "
            f"make: {MOVES_ASKED}?"
        )
    )
    return client.system_one(state={"goal": goal}, questions={"moves": question}).answers["moves"].noul


def read_only(client: DecisionClient, goal: str) -> float:
    """Probability that the goal only asks to find something out, and changes nothing on the way.

    Asked once a run, of the goal alone: a goal that only looks may click with less confidence,
    since a wrong click opens the wrong page and the next step can leave it.
    """
    question = Noul(
        instructions=(
            "Does this goal only ask to find something out, check, or confirm it, so that reaching it "
            "means opening and reading pages without changing, saving, sending, or turning on anything?"
        )
    )
    return client.system_one(state={"goal": goal}, questions={"read_only": question}).answers["read_only"].noul


def verify_typed(client: DecisionClient, goal: str, field_before: Field, typed: str, field_after: Field | None) -> float:
    """Probability that the field now holds a sensible value for its purpose.

    A stand-in field has no value to read back, so `field_after` carries the text the screen shows
    across its row instead (see `actions.read_back`), and nothing says whether it kept the focus.
    An editor reports none either, so it carries the screen's lines that share a word with the
    typing (see `actions.read_editor`).
    """
    after = field_after.value[:300] if field_after else None
    if field_after and field_before.multiline:
        # A text area can hold a whole document, with the typing far past its first lines.
        at = field_after.value.find(typed[:40])
        after = field_after.value[max(0, at - 100) : at + 300] if at >= 0 else after
    if field_before.editor:
        seen = {"screen_lines_sharing_words_with_the_typed_text_now": field_after.value[:1000] if field_after else None}
    elif field_before.clicked:
        seen = {"screen_text_across_the_field_row_now": after}
    else:
        seen = {
            "field_value_now": after,
            "field_still_focused": bool(
                field_after and field_after.role == field_before.role and field_after.label == field_before.label
            ),
        }
    state = {"goal": goal, "field": field_before.summary(), "text_typed": typed, **seen}
    question = Noul(
        instructions=(
            "Did the typing succeed: does the field now contain the typed text, and is that "
            "text a sensible value for what this field asks for, given the goal?"
        )
    )
    return client.system_one(state=state, questions={"ok": question}).answers["ok"].noul

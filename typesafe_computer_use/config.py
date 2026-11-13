"""Tunables, the site catalog, and environment loading."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

MIN_OCR_CONFIDENCE = 0.3
MAX_OPTIONS = 255  # the Choice ceiling of TypeSafe's Jev and of Mercury Decide
ABORT_CORNER_PX = 4
DEFAULT_MIN_CONFIDENCE = 0.4
# The floor for a goal that only asks to find something out, where a wrong click opens the wrong
# page and the next step can leave it. GPT-6 Luna spreads an item's odds over every item on screen:
# its right click scored 0.11 to 0.24 on three Firebase and Cloud Console runs.
DEFAULT_READ_ONLY_CONFIDENCE = 0.15
# How sure the decision model must be that a goal needs a move beyond clicks and typing (for now a keyboard
# shortcut; the click variants and the drag join it in later changes) before those moves are offered for the
# run. A probe of
# Jev scored 20 goals that need one 0.58 to 0.98 and 16 that do not 0.05 to 0.36; offering the moves to every
# goal cost 2.6 points of agreement on saved steps that never needed them.
MOVES_NOUL = 0.5
READ_ONLY_NOUL = 0.8  # how sure the decision model must be that a goal changes nothing before it counts as read-only
# How sure the decision model must be that a goal means opening several things in turn before the writer
# is asked for a plan. Not yet calibrated on a probe of goals; CLICKER_PLAN=on or off settles it without asking.
PLAN_NOUL = 0.5
# What a run may do without asking (CLICKER_PERMISSIONS, or --permissions): `full` takes every action,
# `ask` puts each action that would change something to the user first, `look` never takes one.
PERMISSIONS = ("full", "ask", "look")
# How sure the decision model must be that an action changes something (sends, buys, saves, posts,
# submits) before `ask` or `look` holds it. Not yet calibrated on a probe; unsure holds it.
CHANGES_NOUL = 0.5
DEFAULT_STEPS = 100
DEFAULT_DELAY = 2.0
DEFAULT_HANDOFFS = 10  # each one is a call to the answer model, a few seconds and a few cents
EARLIER_TASKS = 8  # the earlier tasks of a session the writer reads; the thread, not the whole session
# One LLM writes text and reads the screen when the classifier stops, so it has to read screenshots.
DEFAULT_WRITER_MODEL = "claude-sonnet-5"
DEFAULT_BROWSER = "Google Chrome"
ANTHROPIC_HOST = "api.anthropic.com"
WRITER_APIS = ("anthropic", "openai")

# Decisions. OpenRouter's Decisions API serves every decision model under one URL; TypeSafe's own
# API serves Jev. Both take the same request, so the provider is only a URL, a key, and a model id.
DECISION_PROVIDERS = ("openrouter", "typesafe")  # in this order when both keys are set
OPENROUTER_DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"
DEFAULT_OPENROUTER_DECISION_MODEL = "~typesafe/jev-latest"  # or inception/mercury-decide, openai/gpt-6-luna-decisions
TYPESAFE_BASE_URL = "https://api.typesafe.ai"
DEFAULT_TYPESAFE_DECISION_MODEL = "jev-latest"

# The writer on OpenRouter, when OPENROUTER_API_KEY is set and no other writer endpoint is named.
OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1"
DEFAULT_OPENROUTER_WRITER_MODEL = "openai/gpt-6.1-terra"
# For the default model only; a named model keeps its own.
DEFAULT_OPENROUTER_REASONING = "low"
# How OpenRouter may order the answer model's providers: cheapest first, or fastest first.
ANSWER_SORTS = ("price", "throughput")

# Sites the classifier can pick by name. Anything else goes through the writer.
SITES: dict[str, str] = {
    "github": "https://github.com/",
    "gmail": "https://mail.google.com/",
    "google_calendar": "https://calendar.google.com/",
    "launchdarkly": "https://app.launchdarkly.com/",
    "linear": "https://linear.app/",
    "notion": "https://www.notion.so/",
    "slack": "https://app.slack.com/",
    "typesafe_console": "https://console.typesafe.ai/",
}


@dataclass(frozen=True)
class Shortcut:
    """A keyboard shortcut the agent may press, written for a Mac: Command is the key that the other
    platforms' adapters turn into Control, and Control the key that stays Control (see `Desktop.press`)."""

    key: str
    says: str  # what it does, the line the classifier reads
    command: bool = False
    shift: bool = False
    option: bool = False
    control: bool = False
    browser: bool = False  # does its work in a browser only: elsewhere the same keys do something else (Cmd-R is Reply in Mail)


# The apps a browser shortcut (new tab, close tab, next tab, reload) is pressed in; the configured browser counts too.
BROWSER_APPS = ("Google Chrome", "Chromium", "Brave Browser", "Microsoft Edge", "Arc", "Safari", "Firefox")

# The shortcuts the classifier can pick by name, the kind of move that has no control on screen or
# whose control a shortcut reaches in one step. Kept short: each one can split the vote with a button
# that does the same. Nothing that quits, force-quits, logs out, or types text.
SHORTCUTS: dict[str, Shortcut] = {
    "copy": Shortcut("c", "Copy the current selection to the clipboard.", command=True),
    "cut": Shortcut("x", "Cut the current selection to the clipboard.", command=True),
    "paste": Shortcut("v", "Paste the clipboard where the focus is.", command=True),
    "select_all": Shortcut("a", "Select everything in the focused field, document, or page.", command=True),
    "undo": Shortcut("z", "Undo the last change in the app.", command=True),
    # Redo is Command-Shift-Z; the Windows adapter turns it into Ctrl-Shift-Z, which some apps there answer with Ctrl-Y only.
    "redo": Shortcut("z", "Redo the change that was just undone.", command=True, shift=True),
    "save": Shortcut("s", "Save the document that is open.", command=True),
    "find": Shortcut("f", "Open the find bar to search the page or document for text.", command=True),
    "new_tab": Shortcut("t", "Open a new, empty tab in the browser.", command=True, browser=True),
    "close_tab": Shortcut("w", "Close the current tab or window.", command=True, browser=True),
    "next_tab": Shortcut("tab", "Switch to the next tab in the browser.", control=True, browser=True),
    "previous_tab": Shortcut("tab", "Switch to the previous tab in the browser.", control=True, shift=True, browser=True),
    "reload": Shortcut("r", "Reload the page.", command=True, browser=True),
    "zoom_in": Shortcut("=", "Make the page or document larger.", command=True),
    "zoom_out": Shortcut("-", "Make the page or document smaller.", command=True),
    # Added after the one OSWorld task this agent failed, bringing back the last tab that was closed, which no
    # entry above does. They sit in the shortcut question only, a request of its own: the kind question,
    # where each extra entry split the vote, is as it was.
    "reopen_tab": Shortcut("t", "Reopen the tab or window that was closed last.", command=True, shift=True, browser=True),
    "address_bar": Shortcut(
        "l", "Put the cursor in the browser's address bar, with its text selected.", command=True, browser=True
    ),
    "bookmark_page": Shortcut("d", "Bookmark the page that is open.", command=True, browser=True),
    "new_window": Shortcut("n", "Open a new window, or a new document, in the app.", command=True),
    "open_file": Shortcut("o", "Open the dialog that asks which file to open.", command=True),
    "save_as": Shortcut(
        "s",
        "Open the save as dialog, to save the document under a new name or in another place (in some Mac apps this key duplicates the document instead).",
        command=True,
        shift=True,
    ),
    "print": Shortcut("p", "Open the print dialog for the document or page.", command=True),
    "bold": Shortcut("b", "Make the selected text bold, or turn bold on or off at the cursor.", command=True),
    "italic": Shortcut("i", "Make the selected text italic, or turn italics on or off at the cursor.", command=True),
    "underline": Shortcut("u", "Underline the selected text, or turn underline on or off at the cursor.", command=True),
    # Plain navigation keys: they move the focus or the cursor and change nothing, so they are as safe as a scroll.
    "next_field": Shortcut("tab", "Press the Tab key: move the focus to the next field, control, or spreadsheet cell."),
    "previous_field": Shortcut("tab", "Press Shift and Tab: move the focus to the previous field, control, or cell.", shift=True),
    "arrow_up": Shortcut("up", "Press the Up arrow once: move the cursor or the selection up one line, row, or item."),
    "arrow_down": Shortcut("down", "Press the Down arrow once: move the cursor or the selection down one line, row, or item."),
    "arrow_left": Shortcut("left", "Press the Left arrow once: move the cursor or the selection one character or cell left."),
    "arrow_right": Shortcut("right", "Press the Right arrow once: move the cursor or the selection one character or cell right."),
    "page_up": Shortcut("page_up", "Press Page Up: move up by one screen in a document, list, or sheet."),
    "page_down": Shortcut("page_down", "Press Page Down: move down by one screen in a document, list, or sheet."),
}


def load_dotenv(path: Path) -> None:
    """Set KEY=VALUE lines from a .env file into the environment unless already set."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def browser(system_default: str | None = None) -> str:
    """The browser use_browser falls back to: CLICKER_BROWSER, else the system's default browser when
    the adapter can drive it, else Chrome."""
    return os.environ.get("CLICKER_BROWSER") or system_default or DEFAULT_BROWSER


def openrouter_writer() -> bool:
    """Whether the writer goes to OpenRouter: its key is set, and no other writer endpoint is named.

    CLICKER_WRITER_BASE_URL names one; so does ANTHROPIC_BASE_URL, which the Anthropic SDK reads
    with the Anthropic key it belongs to, and CLICKER_WRITER_API=anthropic asks for Anthropic's own.
    ANTHROPIC_BASE_URL with no Anthropic credential beside it names nothing to write with: a coding
    agent's shell sets one for itself, and an app started from there inherits it.
    """
    if not openrouter_key():
        return False
    if os.environ.get("CLICKER_WRITER_API", "").strip().lower() == "anthropic":
        return False
    if os.environ.get("CLICKER_WRITER_BASE_URL"):
        return False
    return not (os.environ.get("ANTHROPIC_BASE_URL") and anthropic_credential())


def openrouter_key() -> bool:
    return bool(os.environ.get("OPENROUTER_API_KEY", "").strip())


def anthropic_credential() -> bool:
    """Whether the Anthropic SDK has a key, token, or profile of its own to send to its base URL."""
    return any(os.environ.get(name, "").strip() for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"))


def writer_model() -> str:
    """The one LLM of a run: it writes free text and proposes URLs, and reads the screen whenever the
    classifier stops (see `answer_model`). CLICKER_WRITER_MODEL names it.

    CLICKER_ANSWER_MODEL named a second model for the reading until the two were made one; it still
    names the LLM when CLICKER_WRITER_MODEL is unset, so an older `.env` keeps the model it chose."""
    default = DEFAULT_OPENROUTER_WRITER_MODEL if openrouter_writer() else DEFAULT_WRITER_MODEL
    return os.environ.get("CLICKER_WRITER_MODEL") or os.environ.get("CLICKER_ANSWER_MODEL") or default


def writer_api() -> str:
    """The API the writer's endpoint speaks: `anthropic` (Messages) or `openai` (Chat Completions).

    OpenRouter speaks the OpenAI one, so that is the default there."""
    api = os.environ.get("CLICKER_WRITER_API", "").strip().lower() or ("openai" if openrouter_writer() else "anthropic")
    if api not in WRITER_APIS:
        raise ValueError(f"CLICKER_WRITER_API must be one of {', '.join(WRITER_APIS)}, not {api!r}")
    return api


def writer_base_url() -> str | None:
    """The endpoint in CLICKER_WRITER_BASE_URL, OpenRouter's (see `openrouter_writer`), or None to
    leave it to the Anthropic SDK.

    The SDK appends the rest of the path, so the full request URL works too: `.../v1/messages`
    comes off for the Anthropic API, `.../chat/completions` for the OpenAI one, which keeps its `/v1`.
    ANTHROPIC_BASE_URL is not read here: the SDK reads it together with the Anthropic credentials,
    so a key and the endpoint it was meant for always travel as a pair.
    """
    raw = os.environ.get("CLICKER_WRITER_BASE_URL")
    if not raw:
        return OPENROUTER_CHAT_URL if openrouter_writer() else None
    base = raw.strip().rstrip("/")
    suffixes = ("/chat/completions",) if writer_api() == "openai" else ("/v1/messages", "/messages", "/v1")
    for suffix in suffixes:
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    return base.rstrip("/") or None


def custom_writer_endpoint() -> bool:
    """Whether the writer talks to anything but Anthropic's own API, by either variable."""
    if writer_api() == "openai":
        return True
    url = writer_base_url() or os.environ.get("ANTHROPIC_BASE_URL")
    return bool(url) and urlparse(url).hostname != ANTHROPIC_HOST


def moves_override() -> bool | None:
    """CLICKER_MOVES: `on` offers every run the moves beyond clicking and typing, `off` offers none,
    whatever the goal says. `auto`, or nothing, leaves it to the decision model (the gate), which is
    how a run decides when nobody forces it. Forcing exists so a benchmark can run the same tasks
    with the moves in and out of the kind question, without the gate's one-call guess in between."""
    raw = os.environ.get("CLICKER_MOVES", "").strip().lower() or "auto"
    if raw not in ("auto", "on", "off"):
        raise ValueError(f"CLICKER_MOVES must be auto, on or off, not {raw!r}")
    return {"on": True, "off": False}.get(raw)


def plan_override() -> bool | None:
    """CLICKER_PLAN: `on` asks the writer for a plan at the start of every run, `off` never does,
    whatever the goal says. `auto`, or nothing, leaves it to the decision model (see `decide.needs_plan`)."""
    raw = os.environ.get("CLICKER_PLAN", "").strip().lower() or "auto"
    if raw not in ("auto", "on", "off"):
        raise ValueError(f"CLICKER_PLAN must be auto, on or off, not {raw!r}")
    return {"on": True, "off": False}.get(raw)


def permissions() -> str:
    """CLICKER_PERMISSIONS: `full` (the default) takes every action the classifier picks, `ask` asks the
    user before an action that would change something, and `look` never takes one, so the run only
    opens, reads, searches and scrolls. The menu bar app's setting writes it to `.env`."""
    raw = os.environ.get("CLICKER_PERMISSIONS", "").strip().lower() or "full"
    if raw not in PERMISSIONS:
        raise ValueError(f"CLICKER_PERMISSIONS must be full, ask or look, not {raw!r}")
    return raw


def writer_vision() -> bool:
    """Whether the answer model gets the screenshot. Off for a model that reads text only."""
    raw = os.environ.get("CLICKER_WRITER_VISION", "").strip().lower() or "true"
    if raw not in ("true", "false", "1", "0", "yes", "no"):
        raise ValueError(f"CLICKER_WRITER_VISION must be true or false, not {raw!r}")
    return raw in ("true", "1", "yes")


def answer_model() -> str:
    """The model that reads the screen when the classifier stops: the writer's own."""
    return writer_model()


def writer_reasoning() -> str | None:
    """The reasoning effort the writer's short calls ask an OpenAI-API model for; None leaves it to the model.

    OpenRouter's default model asks for low effort unless CLICKER_WRITER_REASONING says otherwise."""
    default = DEFAULT_OPENROUTER_REASONING if _openrouter_default(writer_model(), DEFAULT_OPENROUTER_WRITER_MODEL) else None
    return os.environ.get("CLICKER_WRITER_REASONING", "").strip() or default


def answer_reasoning() -> str | None:
    """The same for the calls that read the screen, which judge it and may be worth more thought."""
    default = DEFAULT_OPENROUTER_REASONING if _openrouter_default(answer_model(), DEFAULT_OPENROUTER_WRITER_MODEL) else None
    return os.environ.get("CLICKER_ANSWER_REASONING", "").strip() or default


def writer_provider() -> str | None:
    """The one OpenRouter provider the writer's calls go to, with no fallback; None leaves routing to OpenRouter.

    CLICKER_WRITER_PROVIDER names it, by its OpenRouter slug or tag. The answer model is always
    routed by OpenRouter, in the order `answer_sort` asks for."""
    if not openrouter_writer():
        return None
    return os.environ.get("CLICKER_WRITER_PROVIDER", "").strip() or None


def answer_sort() -> str | None:
    """The order OpenRouter tries the answer model's providers in: `price` for the cheapest first,
    `throughput` for the fastest. None leaves it to OpenRouter's default, which weighs price and uptime.

    OpenRouter still falls back down that order when the first provider fails, so a busy provider
    costs a retry, not the call."""
    if not openrouter_writer():
        return None
    raw = os.environ.get("CLICKER_ANSWER_SORT", "").strip().lower()
    if raw and raw not in ANSWER_SORTS:
        raise ValueError(f"CLICKER_ANSWER_SORT must be one of {', '.join(ANSWER_SORTS)}, not {raw!r}")
    return raw or None


def _openrouter_default(model: str, default: str) -> bool:
    return openrouter_writer() and model == default


def email() -> str | None:
    return os.environ.get("CLICKER_EMAIL") or None

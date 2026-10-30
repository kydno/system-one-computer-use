"""Tunables, the site catalog, and environment loading."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

MIN_OCR_CONFIDENCE = 0.3
MAX_OPTIONS = 255  # the Choice ceiling of TypeSafe's Jev and of Mercury Decide
ABORT_CORNER_PX = 4
DEFAULT_MIN_CONFIDENCE = 0.4
DEFAULT_STEPS = 100
DEFAULT_DELAY = 2.0
DEFAULT_HANDOFFS = 10  # each one is a call to the answer model, a few seconds and a few cents
DEFAULT_WRITER_MODEL = "claude-haiku-4-5"
DEFAULT_ANSWER_MODEL = "claude-sonnet-5"  # runs only when the classifier stops, on a screenshot: worth a stronger reader
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
DEFAULT_OPENROUTER_WRITER_MODEL = "inception/mercury-3"  # short text calls: a fast, cheap model
DEFAULT_OPENROUTER_ANSWER_MODEL = "openai/gpt-6.1-terra"
# For the default models only; a named model keeps its own.
DEFAULT_OPENROUTER_WRITER_REASONING = "medium"
DEFAULT_OPENROUTER_ANSWER_REASONING = "low"
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
    """
    if not os.environ.get("OPENROUTER_API_KEY", "").strip():
        return False
    if os.environ.get("CLICKER_WRITER_API", "").strip().lower() == "anthropic":
        return False
    return not (os.environ.get("CLICKER_WRITER_BASE_URL") or os.environ.get("ANTHROPIC_BASE_URL"))


def writer_model() -> str:
    default = DEFAULT_OPENROUTER_WRITER_MODEL if openrouter_writer() else DEFAULT_WRITER_MODEL
    return os.environ.get("CLICKER_WRITER_MODEL") or default


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


def writer_vision() -> bool:
    """Whether the answer model gets the screenshot. Off for a model that reads text only."""
    raw = os.environ.get("CLICKER_WRITER_VISION", "").strip().lower() or "true"
    if raw not in ("true", "false", "1", "0", "yes", "no"):
        raise ValueError(f"CLICKER_WRITER_VISION must be true or false, not {raw!r}")
    return raw in ("true", "1", "yes")


def answer_model() -> str:
    default = DEFAULT_OPENROUTER_ANSWER_MODEL if openrouter_writer() else DEFAULT_ANSWER_MODEL
    return os.environ.get("CLICKER_ANSWER_MODEL") or default


def writer_reasoning() -> str | None:
    """The reasoning effort the writer's short calls ask an OpenAI-API model for; None leaves it to the model.

    OpenRouter's default writer asks for medium effort unless CLICKER_WRITER_REASONING says otherwise."""
    default = (
        DEFAULT_OPENROUTER_WRITER_REASONING if _openrouter_default(writer_model(), DEFAULT_OPENROUTER_WRITER_MODEL) else None
    )
    return os.environ.get("CLICKER_WRITER_REASONING", "").strip() or default


def answer_reasoning() -> str | None:
    """The same for the answer model, which judges the screen and may be worth more thought."""
    default = (
        DEFAULT_OPENROUTER_ANSWER_REASONING if _openrouter_default(answer_model(), DEFAULT_OPENROUTER_ANSWER_MODEL) else None
    )
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

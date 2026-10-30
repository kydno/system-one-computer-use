"""Command-line entry points: `clicker` and `clicker-inspect`."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import config
from .actions import Context
from .decisions import Endpoint, endpoint
from .events import Events
from .perception import capture, perceive
from .platform_adapter import desktop
from .report import annotate, ax_count, render_payload
from .runner import RunConfig, run
from .timing import format_timing
from .writer import make_writer, provider

DOTENV = Path.cwd() / ".env"


def _prepare() -> Endpoint:
    """The decision endpoint the environment and ./.env configure; the run stops here without one."""
    config.load_dotenv(DOTENV)
    try:
        return endpoint()
    except ValueError as e:
        sys.exit(str(e))


def ask_user(question: str) -> str:
    """Read the user's reply to a question the run has just printed. An empty reply declines to answer.

    The bell is for a user who is watching the browser, not this terminal.
    """
    try:
        return input("\a  > ")
    except EOFError:
        return ""


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="clicker",
        description="Drive this computer toward a goal: screen OCR, a decision-model classifier, deterministic actions.",
    )
    parser.add_argument("goal", help="what you want done on this computer")
    parser.add_argument("--act", action="store_true", help="actually click and type (default: dry run, one step)")
    parser.add_argument("--steps", type=int, default=config.DEFAULT_STEPS, help="max actions before stopping")
    parser.add_argument("--min-confidence", type=float, default=config.DEFAULT_MIN_CONFIDENCE, help="stop below this confidence")
    parser.add_argument(
        "--delay",
        type=float,
        default=config.DEFAULT_DELAY,
        help="most seconds to wait after each action for the screen to settle",
    )
    parser.add_argument(
        "--handoffs",
        type=int,
        default=config.DEFAULT_HANDOFFS,
        help="times the writer may send a stopped run back to the classifier with a new focus (0: every stop is final)",
    )
    parser.add_argument("--out", type=Path, default=Path("runs") / time.strftime("%Y%m%d-%H%M%S"), help="run folder")
    parser.add_argument("--image", type=Path, help="replay a saved capture instead of the live screen (never acts)")
    parser.add_argument("--app", help="frontmost app to report during replay")
    parser.add_argument("--url", help="browser URL to report during replay")
    parser.add_argument(
        "--events",
        action="store_true",
        help="report as JSON lines on stdout and read replies to questions from stdin, for a front end such as the menu bar app",
    )
    args = parser.parse_args(argv)
    events = Events() if args.events else None
    say = print if events is None else events.line

    say(f"classifier: {_prepare().describe()}")
    if args.act and not desktop.accessibility_trusted():
        sys.exit(
            "this terminal, or the app that started clicker, lacks Accessibility permission; "
            "grant it in System Settings > Privacy & Security"
        )
    try:
        writer = make_writer()
        config.writer_vision()  # a bad value stops the run here, not at its first stop
    except ValueError as e:
        sys.exit(str(e))
    if writer is None:
        say(
            "writer disabled: no OPENROUTER_API_KEY, ANTHROPIC_API_KEY or CLICKER_WRITER_BASE_URL; "
            "type_text, writer-proposed URLs and the final answer need one"
        )
    else:
        say(f"writer: {provider(writer)}")

    cfg = RunConfig(
        goal=args.goal,
        out=args.out,
        act=args.act,
        steps=args.steps,
        min_confidence=args.min_confidence,
        delay=args.delay,
        handoffs=args.handoffs,
        image=args.image,
        app=args.app,
        url=args.url,
    )

    # A front end can always answer; a terminal only when someone is at it.
    ask = events.ask if events is not None else ask_user if sys.stdin.isatty() else None

    browser, browsers = config.browser(desktop.default_browser()), tuple(desktop.installed_browsers())
    apps = tuple(desktop.installed_apps())

    def ctx_factory(typesafe, history):
        return Context(
            goal=args.goal,
            browser=browser,
            email=config.email(),
            typesafe=typesafe,
            writer=writer,
            history=history,
            ask=ask,
            browsers=browsers,
            apps=apps,
        )

    state = run(cfg, ctx_factory, events)
    if state.outcome.startswith("aborted"):
        sys.exit(130)


def inspect(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="clicker-inspect",
        description="Count down, capture the screen, and show exactly what the clicker would send to the classifier.",
    )
    parser.add_argument("goal", nargs="?", default="(no goal given)")
    parser.add_argument("--countdown", type=int, default=3)
    parser.add_argument("--no-open", action="store_true", help="write files without opening them")
    parser.add_argument("--out", type=Path, default=Path("inspections") / time.strftime("%Y%m%d-%H%M%S"))
    args = parser.parse_args(argv)
    config.load_dotenv(DOTENV)
    args.out.mkdir(parents=True, exist_ok=True)

    for n in range(args.countdown, 0, -1):
        print(f"{n}...", end=" ", flush=True)
        time.sleep(1)
    print("capture")

    browser, browsers = config.browser(desktop.default_browser()), tuple(desktop.installed_browsers())
    apps = tuple(desktop.installed_apps())
    timing: dict[str, float] = {}
    screen = capture(browser=browser, timing=timing, browsers=browsers)
    items = perceive(screen, config.MAX_OPTIONS, args.goal, timing)
    annotated = args.out / "annotated.png"
    text = args.out / "state.txt"
    screen.image.save(args.out / "raw.png")
    annotate(screen, items, chosen="", out=annotated)
    text.write_text(
        render_payload(args.goal, screen, items, [], browser, config.email(), browsers=browsers, apps=apps), encoding="utf-8"
    )

    print(
        f"app={screen.app!r} url={screen.url!r} items={len(items)} ax={ax_count(items)} "
        f"offscreen={len(screen.offscreen)} field={screen.field.role if screen.field else None}"
    )
    print(format_timing(timing))
    print(f"  {annotated}\n  {text}")
    if not args.no_open:
        desktop.open_path(annotated)
        desktop.open_path(text, as_text=True)

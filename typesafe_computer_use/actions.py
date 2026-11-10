"""Execute one decided action. Every function returns a one-line description for the history."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace

from PIL import Image, ImageChops

from .config import SHORTCUTS, SITES
from .decide import OFFSCREEN_PREFIX, Decision, row_mates, verify_typed
from .decisions import DecisionClient, DecisionError
from .models import MENU_BAR_PT, Field, Guidance, Item, Missed, Popup, Screen
from .platform_adapter import desktop
from .writer import Writer, WriterError, compose_text, compose_url

VERIFY_THRESHOLD = 0.5
WAIT_SECONDS = 3.0  # what a wait adds to the settle every step already gets; three of them cover a slow page
CLOSE_SECONDS = 0.5  # for a closed popup to leave the screen before the click under it
PRESS_SECONDS = 0.4  # for a page to paint what an accessibility press did; Chromium paints within a frame or two
# A press shows when at least this many pixels of the half-size capture moved by more than PIXEL_STEP
# grey levels. On Google Flights, presses that did nothing moved 0 to 40 and real clicks over 3000.
PIXEL_STEP = 24
CHANGED_PIXELS = 100
SCROLL_REACH = (160, 200)  # half the width and height, in points, of the box around the pointer a scroll must change
SCROLL_LINES = 10  # one scroll, in lines; a screen or so of a web page
QUOTES = "'\"\u201c\u201d\u2018\u2019"  # the marks a writer may quote an item's text in
SCROLLS_TO_END = 15  # the most scrolls a writer's "top" or "bottom" takes before it stops anyway
OPEN_SECONDS = 10.0  # for an app that was not running to start and come to the front; Photos takes a few seconds cold
CARET_SECONDS = 0.2  # for a document to report where arrow keys left its caret
CARET_WALK = 600  # the most Right presses that take the caret to its paragraph's end; past that it is refused


@dataclass(frozen=True)
class Context:
    goal: str
    browser: str
    email: str | None
    typesafe: DecisionClient  # the classifier, on OpenRouter or TypeSafe
    writer: Writer | None
    history: list[str]
    ask: Callable[[str], str] | None = None  # puts the writer's question to the user; None when nobody is there to answer
    guidance: Guidance = field(default_factory=Guidance)  # the runner replaces the context when the writer or the user adds to it
    browsers: tuple[str, ...] = ()  # the installed browsers use_browser may work in besides `browser`
    apps: tuple[str, ...] = ()  # the installed apps open_app may open; none, and it is not offered
    earlier: list[dict] = field(default_factory=list)  # the screens before this one, for text that was read on the way


def perform(decision: Decision, screen: Screen, items: list[Item], ctx: Context) -> str:
    desktop.check_abort()
    key = decision.chosen
    by_index = {str(it.index): it for it in items}
    if key in by_index:
        what = click_item(by_index[key], screen)
        mates = row_mates(items, limit=None).get(int(key))
        # Three rows each end in a Buy: the line must say which, or trying one marks them all as tried.
        # The whole row goes in, so two rows that open alike still get lines of their own.
        return f"{what} beside {', '.join(repr(m) for m in mates)}" if mates else what
    if key.startswith(OFFSCREEN_PREFIX):
        return press_offscreen(key[len(OFFSCREEN_PREFIX) :], screen)
    handler = _HANDLERS.get(key)
    if handler is None:
        raise ValueError(f"unknown action {key!r}")
    return handler(decision, screen, items, ctx)


def click_item(item: Item, screen: Screen) -> str:
    """Press an item the app declared through the accessibility tree; click the pixel under it otherwise.

    A press goes to the control itself, so it lands even when the center of the box is covered by
    a sticky header, a cookie banner, or a tooltip. An element that refuses still has a location,
    and so does a web element that takes the press and does nothing with it (see `press_showed`).
    A click there would land on a popup in front of the item, so that popup is closed first.
    """
    ref = screen.ax_refs.get(item.index)
    unseen = False
    if ref is not None and desktop.ax_press(ref):
        if press_showed(screen):
            return f"pressed {item.text!r} via accessibility"
        unseen = True
    popup = screen.covered.get(item.index)
    closed = f"{close_popup(popup)} then " if popup is not None else ""
    try:
        desktop.click_at(screen.to_points(item))
    except Missed as e:
        return f"{closed}click refused: {item.text!r} was not clicked, {e}"
    if ref is None:
        return f"{closed}clicked {item.text!r}"
    if unseen:
        return f"{closed}clicked {item.text!r} (accessibility press changed nothing on screen)"
    return f"{closed}clicked {item.text!r} (accessibility press did not take)"


def press_showed(screen: Screen) -> bool:
    """Whether the screen changed after an accessibility press on a web page.

    Chromium accepts AXPress on any page element and reports success, but a page that listens for
    pointer events instead of clicks does nothing: every press on Google Flights' calendar days and
    Return field left the screen as it was, and the run went on as if they had landed. So a press in
    a browser has to show on screen, against the capture the step decided on. The menu bar is left
    out, since its clock moves, and so is the focused field, since its caret blinks. Outside a web
    page the press goes to the control's own action and is taken at its word.
    """
    if screen.url is None:
        return True
    desktop.sleep_watching(PRESS_SECONDS)
    return moved(screen.image, desktop.screenshot(), screen.scale, screen.field)


def moved(
    before: Image.Image,
    after: Image.Image,
    scale: float,
    field: Field | None = None,
    within: tuple[float, float, float, float] | None = None,
) -> bool:
    """Whether two captures of the display differ by more than a clock tick or a caret blink.

    The menu bar never counts, since its clock moves on its own. A focused field is left out when
    given, for a caret blinks bigger in some fields than in others. `within` (x1, y1, x2, y2 in
    points) looks at that box alone. Captures of different sizes are different screens.
    """
    if after.size != before.size:
        return True
    diff = ImageChops.difference(before.convert("L"), after.convert("L"))
    diff.paste(0, (0, 0, diff.width, round(MENU_BAR_PT * scale)))
    if field is not None:
        pad = 8
        box = (
            (field.x - pad) * scale,
            (field.y - pad) * scale,
            (field.x + field.w + pad) * scale,
            (field.y + field.h + pad) * scale,
        )
        diff.paste(0, tuple(max(0, round(v)) for v in box))
    if within is not None:
        diff = diff.crop(tuple(round(v * scale) for v in within))  # past the edge reads as unchanged
    changed = diff.reduce(2).point(lambda v: 255 if v > PIXEL_STEP else 0).histogram()[255]
    return changed >= CHANGED_PIXELS


def close_popup(popup: Popup) -> str:
    """Close a popup with its own close button, or with Escape when it has none, and give it a moment
    to go. Never with any of its other buttons: those answer it, as 'Restore' restores the last
    session's tabs."""
    button = popup.close
    if button is not None:
        try:
            desktop.click_at((button.x + button.w / 2, button.y + button.h / 2))
        except Missed:
            button = None  # the pointer never got there
    if button is None:
        desktop.press("escape")
    desktop.sleep_watching(CLOSE_SECONDS)
    return f"closed {popup.title}" if button is not None else f"closed {popup.title} with Escape"


def press_offscreen(key: str, screen: Screen) -> str:
    """Press a control the app exposes but does not show.

    AXPress does not need the element to be visible: a note row scrolled thousands of points down
    and a link the browser parked above the viewport both take it. There is no pixel to fall back
    on, so a refusal is the end of it and reads as a no-op.
    """
    nodes = screen.offscreen
    node = nodes[int(key)] if key.isdigit() and int(key) < len(nodes) else None
    if node is None:
        return f"press_offscreen refused: there is no off-screen control {key!r}"
    if desktop.ax_press(node.ref):
        return f"pressed {node.label!r} (off-screen control) via accessibility"
    return f"press_offscreen refused: {node.label!r} did not accept the press"


def fill_field(field: Field, text: str) -> str:
    """Put text in the focused field, by value if the element accepts one and keystrokes otherwise.

    Setting the value is one message instead of one per character, and it cannot be stolen by a
    page that moves the focus mid-word. It is also widely ignored, so the value is read back and
    only a field that really holds the text counts. Keystrokes land after whatever the field
    holds, including a value the element took but did not read back, so the field is always
    emptied first. Returns which path ran, for the history.

    An editor holds a document, which Select All and Delete would wipe and a value would replace,
    so text goes in at its caret by keystrokes alone. So does a text area: once a page is in
    accessibility, a Google Doc's whole body is one AXTextArea named "Document content", and a
    run asked to answer a question in the doc replaced the document with the answer. A text area
    that is a form's comment box loses nothing by it, since an empty one types the same either way.
    """
    if field.multiline:
        desktop.type_text(text)
        return "at the caret via keystrokes"
    ref = field.ref
    if ref is not None:
        desktop.ax_focus(ref)
        if desktop.ax_set_value(ref, text):
            back = desktop.ax_value(ref)
            if back is not None and back.endswith(text):
                return "via accessibility"
    desktop.clear_field()
    desktop.type_text(text)
    return "via keystrokes"


def paragraph_end(value: str, caret: int) -> int | None:
    """Where the paragraph holding `caret` ends in `value`, or None when that paragraph is blank."""
    start = value.rfind("\n", 0, caret) + 1
    end = value.find("\n", caret)
    end = len(value) if end < 0 else end
    return end if value[start:end].strip() else None


def make_line(field: Field, pid: int | None) -> bool | None:
    """Put the caret on a line of its own after the paragraph it sits in, when that paragraph has text.

    A click on a document's text leaves the caret inside it: answering question 1 of a reading
    guide wrote the answer into the middle of the question. So the caret walks to the end of its
    paragraph by Right presses, which every editor moves by, and the element's own report says
    whether it got there before Shift-Return opens the line. Shift-Return, not Return: Return in a
    numbered list starts a new item and renumbers every question after it, and in a chat box it
    sends. True when a line was made, False when the caret was already where text belongs (a blank
    line, an empty field, or an editor that reports no caret), and None when the caret could not
    be brought to the paragraph's end, which leaves it there and types nothing.
    """
    if field.caret is None or not field.value.strip():
        return False
    end = paragraph_end(field.value, field.caret)
    if end is None:
        return False
    steps = end - field.caret
    if steps > CARET_WALK:
        return None
    for _ in range(steps):
        desktop.press("right")
    desktop.sleep_watching(CARET_SECONDS)
    now = desktop.focused_field(pid)
    if now is None or now.caret != end:
        return None
    desktop.press("return", shift=True)
    return True


def read_back(field: Field) -> Field:
    """A stand-in field, holding the text the screen now shows across its row, left to right.

    The browser reports nothing about the box, so the screen is the only witness to what went in.
    The box is the text that was clicked, often a label beside the input or a value at one end of
    it, so the row is read across the whole display, from one box height above to one below.
    """
    image = desktop.screenshot()
    scale = desktop.display_scale(image)
    top = max(0, round((field.y - field.h) * scale))
    bottom = min(image.height, round((field.y + 2 * field.h) * scale))
    if bottom <= top:
        return replace(field, value="")
    lines = desktop.recognize_text(image.crop((0, top, image.width, bottom)))
    return replace(field, value=" | ".join(text for text, _, _ in sorted(lines, key=lambda line: line[2][0])))


def read_editor(field: Field, typed: str) -> Field:
    """The editor, holding the screen's lines that share a word with the typed text, top to bottom.

    An editor such as a Google Doc draws its text itself and reports none, and its focused box is a
    hidden one with no place on the page, so the whole screen is read and only the lines that could
    be the typing are kept.
    """
    words = set(re.findall(r"\w{3,}", typed.lower()))
    lines = desktop.recognize_text(desktop.screenshot())
    kept = [
        text
        for text, _, _ in sorted(lines, key=lambda line: (line[2][1], line[2][0]))
        if words & set(re.findall(r"\w{3,}", text.lower()))
    ]
    return replace(field, value=" | ".join(kept))


def restore_field(field: Field, typed: str) -> bool:
    """Undo only our write, through the original element, never through the current focus.

    If the element disappeared or its value changed again, leave it alone. A failed AX restore
    has no keyboard fallback: Select All/Delete could destroy an unrelated field's contents.
    """
    ref = field.ref
    if ref is None or desktop.ax_value(ref) != typed:
        return False
    return desktop.ax_set_value(ref, field.value) and desktop.ax_value(ref) == field.value


def _use_browser(decision: Decision, screen, items, ctx: Context) -> str:
    """Go to the browser the browser answer named, and open the website the site answer named.

    No browser answer means one browser to work in, the configured one. `none` is the page already
    open there, so bringing the browser forward is the whole action. A catalog key is its URL, and
    `other` is a site outside the catalog, which only the writer can name. The writer reads the
    browser's open tabs too, since the page a goal is about is often one the user already has open
    behind another tab, and a URL it names from them is shown in its own tab, not opened again.
    Opening a URL activates the browser too, so the three cases differ only in the page.
    """
    browser = decision.browser.choice if decision.browser is not None else ctx.browser
    site = decision.site.choice
    if site == "none":
        if desktop.activate(browser):
            return f"activated {browser}"
        return f"use_browser failed: {browser} did not come to the front"
    url = SITES.get(site)
    tabs: list[tuple[str, str]] = []
    if url is None:
        if ctx.writer is None:
            return "use_browser refused: the site is outside the catalog and no writer is available to propose a URL"
        tabs = desktop.browser_tabs(browser)
        try:
            url = compose_url(ctx.writer, ctx.goal, ctx.history, ctx.guidance, tabs)
        except WriterError as e:
            return f"use_browser refused: the writer failed ({e})"
    if not url:
        return "use_browser refused: the writer proposed no usable URL for this goal"
    if any(open_url == url for _, open_url in tabs) and desktop.show_tab(browser, url):
        return f"switched to the open tab {url}" + ("" if browser == ctx.browser else f" in {browser}")
    if desktop.open_url(browser, url):
        return f"opened {url}" if browser == ctx.browser else f"opened {url} in {browser}"
    return f"use_browser failed: opened {url} but {browser} did not come to the front"


def _open_app(decision: Decision, screen, items, ctx: Context) -> str:
    """Bring the app the app answer named to the front, starting it when it is not running.

    `none` means no installed app is the one the goal needs, and the history line says so, so the
    next step does not ask again.
    """
    app = decision.app.choice if decision.app is not None else "none"
    if app not in ctx.apps:
        return "open_app refused: no installed app is the one the goal needs"
    if app == screen.app:
        return f"open_app refused: {app} is already in front"
    if desktop.activate(app, timeout=OPEN_SECONDS):
        return f"opened {app}"
    return f"open_app failed: {app} did not come to the front with a window"


def _press_shortcut(decision: Decision, screen, items, ctx: Context) -> str:
    """Press the shortcut the shortcut answer named, from the catalog and nowhere else.

    `none` means no shortcut in the list is the one the goal needs, and the history line says so, so
    the next step does not ask again. What the keys did shows on the next capture, which is the only
    witness: a copy changes nothing on screen, and the idle count bounds a run that only copies.
    """
    name = decision.shortcut.choice if decision.shortcut is not None else "none"
    shortcut = SHORTCUTS.get(name)
    if shortcut is None:
        return "press_shortcut refused: no shortcut in the list is the one the goal needs"
    desktop.press(shortcut.key, command=shortcut.command, shift=shortcut.shift, option=shortcut.option, control=shortcut.control)
    return f"pressed the {name.replace('_', ' ')} shortcut"


def _type_email(decision, screen: Screen, items, ctx: Context) -> str:
    if not (screen.field and screen.field.is_text):
        return "type_email refused: no text field is focused"
    how = fill_field(screen.field, ctx.email or "")
    return f"typed email {how}"


def _type_text(decision, screen: Screen, items, ctx: Context) -> str:
    """Fill the focused field with the writer's text, and check it, or submit it with Return.

    Text the writer submits is not checked: Return usually takes the field away (a dialog closes, a
    search runs), so a read after it no longer shows the field, and a read before it would split
    the keystrokes and the Return into two OSWorld steps. The next screen says whether it took.
    """
    if not (screen.field and screen.field.is_text):
        return "type_text refused: no text field is focused"
    if ctx.writer is None:
        return "type_text refused: no writer available"
    try:
        fill = compose_text(ctx.writer, ctx.goal, screen, items, ctx.history, ctx.guidance, ctx.earlier)
    except WriterError as e:
        return f"type_text refused: the writer failed ({e})"
    text = fill.text
    if not text:
        why = f" ({fill.reason})" if fill.reason else ""
        return f"type_text refused: writer declined to fill this field{why}"
    line = make_line(screen.field, screen.pid) if screen.field.multiline else False
    if line is None:
        return "type_text refused: the caret is inside text and could not be moved to the end of its paragraph"
    how = ("on a new line " if line else "") + fill_field(screen.field, text)
    if fill.submit:
        desktop.press("return")
        return f"typed {text!r} into {screen.field.label!r} {how} and pressed Return"
    time.sleep(0.3)
    try:
        if screen.field.editor:
            after = read_editor(screen.field, text)
        elif screen.field.clicked:
            after = read_back(screen.field)
        else:
            after = desktop.focused_field(screen.pid)
        p = verify_typed(ctx.typesafe, ctx.goal, screen.field, text, after)
    except DecisionError as e:
        return f"typed {text!r} into {screen.field.label!r} {how} (not verified: {e})"
    if p < VERIFY_THRESHOLD:
        recovery = "restored previous value" if restore_field(screen.field, text) else "could not safely restore previous value"
        return f"typed {text!r} into {screen.field.label!r} {how} but verification failed ({p:.2f}); {recovery}"
    return f"typed {text!r} into {screen.field.label!r} {how} (verified {p:.2f})"


def _key(name: str, description: str, command: bool = False):
    def handler(decision, screen, items, ctx) -> str:
        desktop.press(name, command)
        return description

    return handler


def _scroll(lines: int, description: str):
    """Scroll over the item the classifier picked, and say so when nothing there moved.

    A wheel event scrolls whatever is under the pointer. On Google Maps the window's center is the
    map, so sixteen scrolls aimed there zoomed out to the whole East Coast while the results list
    beside it never moved, and every one read "scrolled down". The item question names the part of
    the screen to scroll, so the pointer goes there; with no item, it goes to the window's center
    as before.
    """

    def handler(decision, screen, items, ctx) -> str:
        target = scroll_target(decision, screen, items)
        point = screen.to_points(target) if target is not None else None
        before = hovered(point) if point is not None else screen.image
        desktop.scroll(lines, point)
        what = f"{description} over {target.text!r}" if target is not None else description
        return what if scroll_showed(screen, before, point) else f"{what} (nothing there moved)"

    return handler


def scroll_target(decision: Decision, screen: Screen, items: list[Item]) -> Item | None:
    """The item the classifier picked, when a wheel there can reach the app."""
    if decision.item is None:
        return None
    item = next((it for it in items if str(it.index) == decision.item.choice), None)
    return item if item is not None and wheel_reaches(item, screen) else None


def wheel_reaches(item: Item, screen: Screen) -> bool:
    """Whether a wheel over `item` reaches the app: not over the menu bar, and not outside the
    frontmost window when its bounds are known."""
    if screen.in_menu_bar(item):
        return False
    if screen.window is not None:
        x, y = screen.to_points(item)
        wx, wy, ww, wh = screen.window
        if not (wx <= x <= wx + ww and wy <= y <= wy + wh):
            return False
    return True


def writer_scroll(way: str, over: str, screen: Screen, items: list[Item]) -> str:
    """Scroll as the writer said: "up" or "down" once, "top" or "bottom" until nothing more moves.

    `over` is the text of the item to scroll over, and the window's center when it names none on
    screen. The writer scrolls itself because the classifier would not: on the Firebase console a
    goal about Google Analytics drew its scroll to the sidebar's 'Analytics' link every time, even
    while the writer's focus said to scroll over the settings page.
    """
    lines = SCROLL_LINES if way in ("up", "top") else -SCROLL_LINES
    target = scroll_over(over, screen, items)
    point = screen.to_points(target) if target is not None else None
    before = hovered(point) if point is not None else screen.image
    scrolls = 0
    for _ in range(SCROLLS_TO_END if way in ("top", "bottom") else 1):
        desktop.scroll(lines, point)
        desktop.sleep_watching(PRESS_SECONDS)
        after = desktop.screenshot()
        if not scroll_moved(screen, before, after, point):
            break
        scrolls += 1
        before = after
    where = f" over {target.text!r}" if target is not None else ""
    if way in ("top", "bottom"):
        what = f"scrolled to the {way}{where} ({scrolls} {'scroll' if scrolls == 1 else 'scrolls'})"
    else:
        what = f"scrolled {way}{where}"
    return what if scrolls else f"{what} (nothing there moved)"


def scroll_over(text: str, screen: Screen, items: list[Item]) -> Item | None:
    """The item a writer's scroll names: the one whose text is `text`, else the first that holds it,
    as long as a wheel there reaches the app."""
    wanted = text.strip().strip(QUOTES).casefold()
    if not wanted:
        return None
    exact = [it for it in items if it.text.strip().casefold() == wanted]
    holding = [it for it in items if wanted in it.text.casefold()]
    return next((it for it in exact + holding if wheel_reaches(it, screen)), None)


def hovered(point: tuple[float, float]) -> Image.Image:
    """The display with the pointer parked at `point`, the capture a scroll there is judged against.

    The pointer alone can change the screen. On the Firebase console a scroll aimed at the sidebar's
    'Analytics' link opened its flyout menu, and the change read as the page scrolling up, twice,
    while the page never moved and the setting above stayed out of sight.
    """
    desktop.hover(point)
    desktop.sleep_watching(PRESS_SECONDS)
    return desktop.screenshot()


def scroll_showed(screen: Screen, before: Image.Image, point: tuple[float, float] | None) -> bool:
    """Whether a scroll changed the screen around the pointer, or anywhere when it went to no item,
    from `before`: the capture with the pointer already there, or the step's own when it was not.

    A page at its end, or a view that does not scroll, leaves the screen as it was, and the next
    step should know that rather than read "scrolled down" again.
    """
    desktop.sleep_watching(PRESS_SECONDS)
    return scroll_moved(screen, before, desktop.screenshot(), point)


def scroll_moved(screen: Screen, before: Image.Image, after: Image.Image, point: tuple[float, float] | None) -> bool:
    """Whether the screen changed around the pointer from `before` to `after`, or anywhere with no pointer."""
    if point is None:
        return moved(before, after, screen.scale)
    x, y = point
    dx, dy = SCROLL_REACH
    return moved(before, after, screen.scale, within=(x - dx, y - dy, x + dx, y + dy))


def _wait(decision, screen, items, ctx) -> str:
    """Give a loading page time. The step's own settle follows, and holds out while the page still moves."""
    desktop.sleep_watching(WAIT_SECONDS)
    return "waited"


def wait(screen: Screen, items: list[Item], ctx: Context) -> str:
    """The classifier's own wait, for a stop the writer reads as a screen still loading. Taken from
    the table like any chosen action, so the two are one action."""
    return _HANDLERS["wait"](None, screen, items, ctx)


_HANDLERS = {
    "use_browser": _use_browser,
    "open_app": _open_app,
    "press_shortcut": _press_shortcut,
    "type_email": _type_email,
    "type_text": _type_text,
    "press_enter": _key("return", "pressed Return"),
    "press_escape": _key("escape", "pressed Escape"),
    "go_back": _key("[", "went back", command=True),
    "scroll_down": _scroll(-SCROLL_LINES, "scrolled down"),
    "scroll_up": _scroll(SCROLL_LINES, "scrolled up"),
    "wait": _wait,
}

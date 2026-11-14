"""A deterministic simulated computer, so the real step loop can be driven end to end.

The package is one loop over four seams: capture the screen, perceive items, ask the classifier,
act on the machine. Every unit test here covers one seam; nothing covered the loop itself, where
the stop rules live. So this module fakes the two outer seams -- the screen and the machine -- and
leaves `runner.run`, `decide`, and `actions` exactly as they ship. A scenario then reads as a page
graph plus a policy, and a failure means the architecture, not the harness.

The screen is a page of rows: item N occupies the pixel box (100, 100+40N, 600, 130+40N) on a
2000x1200 capture at scale 2.0, which is what `tests/conftest.py`'s `screen` fixture describes.
Clicks come back as screen points, so the world halves them to find the row they hit.
"""

from __future__ import annotations

import dataclasses
import zlib
from collections.abc import Callable
from dataclasses import dataclass

from PIL import Image

from typesafe_computer_use import actions, runner
from typesafe_computer_use.actions import Context
from typesafe_computer_use.events import Events
from typesafe_computer_use.models import AxNode, Field, Item, Popup, Screen
from typesafe_computer_use.platform_adapter import desktop
from typesafe_computer_use.runner import RunConfig, RunState, run

# The stand-ins for both models live in the package, where the mock OS runs its scripted solutions
# through them too; the tests import them from here, as before.
from typesafe_computer_use.stand_ins import FakeTypeSafe, FakeWriter, Policy, scripted  # noqa: F401

CAPTURE = (2000, 1200)
SCALE = 2.0
ROW_TOP = 100.0  # first row's top edge, in capture pixels
ROW_HEIGHT = 40.0
ROW_TEXT_HEIGHT = 30.0  # a row's text is shorter than its pitch, so there is a gap between rows
ROW_X1, ROW_X2 = 100.0, 600.0
LOADING = "Loading..."
CLICKS = {("left", 1): "click", ("right", 1): "rightclick", ("left", 2): "doubleclick", ("left", 3): "tripleclick"}

# An off-screen control is parked far above the display, the way Chromium parks a scrolled-out link.
OFFSCREEN_Y = -4200.0

Rows = list  # of str, or (text, role)


COLUMN_GAP = 10.0  # the gutter between two columns of one row, so their boxes do not touch


def row_box(n: int) -> tuple[float, float, float, float]:
    """The pixel box of the Nth row, top to bottom."""
    top = ROW_TOP + ROW_HEIGHT * n
    return (ROW_X1, top, ROW_X2, top + ROW_TEXT_HEIGHT)


def cell_box(n: int, k: int, columns: int) -> tuple[float, float, float, float]:
    """The pixel box of column K of N in the Nth row: the row's width, split evenly, minus a gutter.

    A row of one column keeps the whole width, so a page of plain rows lays out exactly as before.
    """
    if columns == 1:
        return row_box(n)
    top = ROW_TOP + ROW_HEIGHT * n
    width = ROW_X2 - ROW_X1
    return (ROW_X1 + width * k / columns, top, ROW_X1 + width * (k + 1) / columns - COLUMN_GAP, top + ROW_TEXT_HEIGHT)


@dataclass(frozen=True)
class Ref:
    """An accessibility element handle, the opaque object an action is sent to.

    The real one is a PyObjC element; here it only has to be the same object every capture and to
    say what it stands for. An element the loop presses is named by the action pressing it applies
    ("click:Tickets"); a text field is named by its label. The world keeps one Ref per name and
    tells the two kinds apart by which cache holds it, so a stray ref reads as neither.
    """

    name: str


@dataclass(frozen=True)
class Cell:
    """One item of the current page: its text, its role, the row it sits in, and its pixel box."""

    text: str
    role: str
    row: int
    box: tuple[float, float, float, float]


@dataclass
class Page:
    """One screen of the simulated computer, and what each action does to it.

    `items` are rows of text, or (text, role) for a control the app declares through accessibility.
    A row that is a list holds several items side by side, laid out left to right across the row:
    ["Bruno Mars", "Sep 25", "Buy"] is one line of a listing. A page whose rows change on their own
    -- a clock, a ticker -- passes a callable(world) instead, which is asked again on every capture.
    `on` maps an action as the world names it ("click:Tickets", "enter", "type:hello", "open:<url>")
    to the next page's name, or to a callable(world) returning a name or None to stay. Text that
    appears more than once on the page cannot name one item, so those clicks are keyed by row
    instead: "click:Buy@1" is the Buy of the second row. An action
    with no entry leaves the page alone, which is the "nothing happened" case the runner must cope
    with.
    """

    name: str
    items: Rows | Callable[[World], Rows] = dataclasses.field(default_factory=list)
    url: str | None = None  # browser pages have one; app pages do not
    app: str = "Google Chrome"
    field: str | None = None  # label of the text field focused on this page, if any
    offscreen: tuple[str, ...] = ()  # labels the app exposes without showing
    loads_in: int = 0  # steps of "wait" before the items appear
    no_ax_value: bool = False  # the field refuses to have its value set, so text has to be typed in
    hides_focus: bool = False  # Chromium with its page kept out of accessibility: the field takes keys but is never reported
    covered_by: str | None = None  # an overlay eating every mouse click: the text of what is really hit
    popup: str | None = None  # a window in front of the page, by name; the row reading "Close" is its close button
    under_popup: tuple[str, ...] = ()  # the page's items under that window, which eats a mouse click on them
    repaints: bool = True  # False: the page shows no band for the actions taken, so one it ignores leaves its pixels as they were
    on: dict[str, str | Callable[[World], str | None]] = dataclasses.field(default_factory=dict)


class World:
    """The pages, which one is showing, what was typed, and every action the world received.

    `log` holds the world's own action names in order. Mouse clicks also land in `mouse` as the raw
    point, because a press through accessibility and a click on the pixel under the item both read
    as "click:<text>" here, and a scenario needs to tell the two apart.

    `typed` is a plain dict a scenario may seed before the run, for a field that already holds
    something when the loop first sees it.
    """

    def __init__(self, pages: list[Page], start: str | None = None):
        self.pages = {p.name: p for p in pages}
        self.page = self.pages[start or pages[0].name]
        self.typed: dict[str, str] = {}
        self.log: list[str] = []
        self.mouse: list[tuple[float, float]] = []
        self.wheel: list[tuple[float, float] | None] = []  # where each scroll parked the pointer, None for the window's center
        self.fake: FakeTypeSafe | None = None  # the classifier `drive` built, for fake.states
        self.apart: list[bool] = []  # whether each step's perception was told to keep a text area's lines apart
        self.asked: list[str] = []  # the questions the writer put to the user
        self.loading = {p.name: p.loads_in for p in pages}
        self.ticks = 0  # captures taken so far, so a page can show something that moves on its own
        self._refs: dict[str, Ref] = {}  # action -> the element, so a ref stays the same object
        self._fields: dict[str, Ref] = {}  # label -> the field's element

    # ----- the world's own state ------------------------------------------------------------

    @property
    def loading_now(self) -> bool:
        return self.loading[self.page.name] > 0

    def cells(self) -> list[Cell]:
        """Every item of the current page in reading order. A page still loading shows one line."""
        if self.loading_now:
            return [Cell(LOADING, "", 0, row_box(0))]
        items = self.page.items(self) if callable(self.page.items) else self.page.items
        out = []
        for n, entry in enumerate(items):
            columns = entry if isinstance(entry, list) else [entry]
            for k, cell in enumerate(columns):
                text, role = (cell, "") if isinstance(cell, str) else cell
                out.append(Cell(text, role, n, cell_box(n, k, len(columns))))
        return out

    def click_action(self, cell: Cell, cells: list[Cell]) -> str:
        """The action clicking this cell applies: by text, or by row when the text is not unique."""
        repeated = sum(1 for other in cells if other.text == cell.text) > 1
        return f"click:{cell.text}@{cell.row}" if repeated else f"click:{cell.text}"

    def apply(self, action: str, label: str | None = None, append: bool = False) -> None:
        """Receive one action: record it, then follow the current page's transition for it.

        A page that is still loading answers nothing but `wait`: the tick is spent, the action is
        dropped. That is what a real app does to a click on a spinner.
        """
        self.log.append(action)
        if self.loading_now:
            if action == "wait":
                self.loading[self.page.name] -= 1
            return
        if action.startswith("type:"):
            key = label or self.page.field or ""
            text = action[len("type:") :]
            # Keystrokes land after whatever the field already holds; setting a value replaces it.
            self.typed[key] = self.typed.get(key, "") + text if append else text
        nxt = self.page.on.get(action)
        if callable(nxt):
            nxt = nxt(self)
        if nxt is not None:
            self.page = self.pages[nxt]

    def _ref(self, action: str) -> Ref:
        """The element that applies `action` when pressed, the same object every capture."""
        return self._refs.setdefault(action, Ref(action))

    def _field_ref(self, label: str) -> Ref:
        return self._fields.setdefault(label, Ref(label))

    def _label(self, ref: object) -> str | None:
        """The field this ref stands for, or None when it is not one of this world's fields."""
        return ref.name if isinstance(ref, Ref) and self._fields.get(ref.name) is ref else None

    # ----- the screen ----------------------------------------------------------------------

    def capture(self) -> Screen:
        """What `perception.capture` would return for the page now showing.

        Each capture is a tick, so a page whose rows are a callable can move between steps without
        moving inside one: every other read of the screen in the same step sees the same rows.
        """
        nodes = [
            AxNode(role="AXLink", label=lbl, x=0.0, y=OFFSCREEN_Y, w=120.0, h=32.0, pressable=True, ref=self._ref(f"press:{lbl}"))
            for lbl in self.page.offscreen
        ]
        screen = Screen(
            image=self.drawn(),
            scale=SCALE,
            app=self.page.app,
            field=self.focused_field(),
            url=self.page.url,
            pid=1,
            window=None,
            offscreen=nodes,
        )
        self.ticks += 1
        return screen

    def drawn(self) -> Image.Image:
        """The display as an image: one band whose shade moves with every action the world takes, so
        a press it took shows on the next screenshot, as a page repaints (see `actions.press_showed`); a page
        that does not repaint shows no band, so an action it ignores changes no pixel (see `actions._go_back`).
        Each row is a box shaded by its text, so the rows look the same until the rows change, as a
        list scrolled past its end does (see `actions.scroll_showed`)."""
        image = Image.new("RGB", CAPTURE)
        if self.page.repaints:
            shade = len(self.log) * 40 % 256
            image.paste((shade, shade, shade), (0, CAPTURE[1] // 2, CAPTURE[0], CAPTURE[1] // 2 + 200))
        for cell in self.cells():
            tone = 40 + zlib.crc32(cell.text.encode()) % 200
            image.paste((tone, tone, tone), tuple(round(v) for v in cell.box))
        return image

    def perceive(self, screen: Screen) -> list[Item]:
        """The rows as items, filling `screen.ax_refs` for the ones the app declared, and
        `screen.covered` for the ones under the page's popup.

        A control under a popup is found in the tree but not pressed through it, as in an OSWorld VM:
        a press would reach it through the popup and leave nothing for the loop to get around.
        """
        screen.ax_refs.clear()
        screen.covered.clear()
        items = []
        cells = self.cells()
        popup = self.popup(cells)
        for n, cell in enumerate(cells):
            items.append(Item(n, cell.text, 1.0, *cell.box, role=cell.role, source="ax" if cell.role else "ocr"))
            if popup is not None and cell.text in self.page.under_popup:
                screen.covered[n] = popup
            elif cell.role:
                screen.ax_refs[n] = self._ref(self.click_action(cell, cells))
        return items

    def popup(self, cells: list[Cell]) -> Popup | None:
        """The page's popup, over the whole capture, with the row reading "Close" as its close button."""
        if self.page.popup is None or self.loading_now:
            return None
        close = next((c for c in cells if c.text == "Close"), None)
        button = None
        if close is not None:
            x1, y1, x2, y2 = (v / SCALE for v in close.box)
            button = AxNode(role="AXButton", label="Close", x=x1, y=y1, w=x2 - x1, h=y2 - y1, pressable=False)
        return Popup(self.page.popup, 0.0, 0.0, CAPTURE[0] / SCALE, CAPTURE[1] / SCALE, close=button)

    def focused_field(self, pid: int | None = None) -> Field | None:
        """The page's text field, at the row that carries its label.

        A field is placed by the row that reads as its label, so a page that names a field it does
        not show is a mistake in the scenario rather than a case the world has to invent a box for.
        """
        label = self.page.field
        if label is None or self.page.hides_focus:
            return None
        labelled = next((c for c in self.cells() if c.text == label), None)
        if labelled is None:
            raise AssertionError(f"page {self.page.name!r} has a field {label!r} but no row reads it")
        x1, top, x2, _ = labelled.box
        return Field(
            role="AXTextField",
            label=label,
            placeholder="",
            value=self.typed.get(label, ""),
            x=x1 / SCALE,
            y=top / SCALE,
            w=(x2 - x1) / SCALE,
            h=ROW_TEXT_HEIGHT / SCALE,
            ref=self._field_ref(label),
        )

    def recognize_text(self, image: Image.Image) -> list[tuple[str, float, tuple[float, float, float, float]]]:
        """OCR of the row the page's field sits in: its label, then what it holds now.

        The world does not track which strip of the screen was cropped, and the one caller reads the
        field's row, so that row is what it gets.
        """
        label = self.page.field
        row = next((c for c in self.cells() if c.text == label), None)
        if row is None:
            return []
        _, y1, x2, y2 = row.box
        lines = [(c.text, 1.0, c.box) for c in self.cells() if c.row == row.row]
        held = self.typed.get(label or "", "")
        return lines + ([(held, 1.0, (x2 + 1, y1, x2 + 100, y2))] if held else [])

    # ----- the machine ---------------------------------------------------------------------

    def click_at(self, point: tuple[float, float], button: str = "left", count: int = 1) -> None:
        """A synthetic click, in screen points: find the cell it lands on and press that item.

        A page with a `covered_by` overlay takes every mouse click itself, wherever it was aimed:
        that is a cookie banner over the content. A press through accessibility still reaches the
        element under it, which is the whole point of pressing rather than clicking. A right click
        or a click that repeats is the action of the same name ("rightclick:Photo", "doubleclick:Photo").
        """
        self.mouse.append(point)
        way = CLICKS[button, count]
        if self.page.covered_by is not None:
            self.apply(f"{way}:{self.page.covered_by}")
            return
        hit, cells = self.cell_at(point)
        if hit is not None and self.page.popup is not None and hit.text in self.page.under_popup:
            self.apply(f"click:{self.page.popup}")  # the popup is in front of it and takes the click
            return
        self.apply(self.click_action(hit, cells).replace("click:", f"{way}:", 1) if hit is not None else f"{way}:nothing")

    def cell_at(self, point: tuple[float, float]) -> tuple[Cell | None, list[Cell]]:
        """The cell under a screen point, and every cell of the page."""
        px, py = point[0] * SCALE, point[1] * SCALE
        cells = self.cells()
        return next((c for c in cells if c.box[0] <= px <= c.box[2] and c.box[1] <= py <= c.box[3]), None), cells

    def drag(self, start: tuple[float, float], end: tuple[float, float]) -> None:
        """A drag from one point to another is "drag:<text taken>><text dropped on>"."""
        taken, dropped = (hit.text if hit is not None else "nothing" for hit, _ in (self.cell_at(start), self.cell_at(end)))
        self.mouse.append(start)
        self.apply(f"drag:{taken}>{dropped}")

    def ax_press(self, ref: object) -> bool:
        if not isinstance(ref, Ref) or self._refs.get(ref.name) is not ref:
            return False
        self.apply(ref.name)
        return True

    def press(self, name: str, command: bool = False, shift: bool = False, option: bool = False, control: bool = False) -> None:
        """A key. Command-[ is Back; any other chord with Command, Option or Control is "key:cmd+shift+z",
        its modifiers in that order; a plain key, or one with Shift alone, is the key's own name."""
        if command and name == "[":
            self.apply("back")
            return
        if command or option or control:
            held = [m for m, on in (("cmd", command), ("ctrl", control), ("opt", option), ("shift", shift)) if on]
            self.apply("key:" + "+".join([*held, name]))
            return
        self.apply("enter" if name == "return" else name)

    def scroll(self, lines: int, at: tuple[float, float] | None = None) -> None:
        self.wheel.append(at)
        self.apply("scroll_down" if lines < 0 else "scroll_up")

    def type_text(self, text: str) -> None:
        self.apply(f"type:{text}", append=True)

    def ax_set_value(self, ref: object, text: str) -> bool:
        """Set the field's value, unless the page is one of those that quietly refuse to take one."""
        if self.page.no_ax_value:
            return False
        self.apply(f"type:{text}", label=self._label(ref))
        return True

    def ax_value(self, ref: object) -> str | None:
        return self.typed.get(self._label(ref) or "", "")

    def clear_field(self) -> None:
        self.apply("clear_field")
        self.typed.pop(self.page.field or "", None)

    def activate(self, app: str) -> bool:
        self.apply("activate")
        return True

    def open_url(self, browser: str, url: str) -> bool:
        self.apply(f"open:{url}")
        return True

    # ----- wiring --------------------------------------------------------------------------

    def install(self, monkeypatch) -> None:
        """Replace the two outer seams: the screen the loop reads and the machine it drives."""
        monkeypatch.setattr(runner, "capture", lambda *a, **k: self.capture())
        monkeypatch.setattr(
            runner, "perceive", lambda screen, *a, **k: (self.apart.append(k.get("apart", False)), self.perceive(screen))[1]
        )
        monkeypatch.setattr(desktop, "check_abort", lambda: None)
        monkeypatch.setattr(desktop, "sleep_watching", lambda seconds: None)
        monkeypatch.setattr(desktop, "click_at", self.click_at)
        monkeypatch.setattr(desktop, "ax_press", self.ax_press)
        monkeypatch.setattr(desktop, "press", self.press)
        monkeypatch.setattr(desktop, "drag", self.drag)
        monkeypatch.setattr(desktop, "scroll", self.scroll)
        monkeypatch.setattr(desktop, "hover", lambda at: None)  # nothing in the world reacts to the pointer
        monkeypatch.setattr(desktop, "type_text", self.type_text)
        monkeypatch.setattr(desktop, "ax_focus", lambda ref: True)
        monkeypatch.setattr(desktop, "ax_set_value", self.ax_set_value)
        monkeypatch.setattr(desktop, "ax_value", self.ax_value)
        monkeypatch.setattr(desktop, "clear_field", self.clear_field)
        monkeypatch.setattr(desktop, "focused_field", self.focused_field)
        monkeypatch.setattr(desktop, "screenshot", self.drawn)
        monkeypatch.setattr(desktop, "display_scale", lambda image: SCALE)
        monkeypatch.setattr(desktop, "recognize_text", self.recognize_text)
        monkeypatch.setattr(desktop, "activate", self.activate)
        monkeypatch.setattr(desktop, "open_url", self.open_url)
        monkeypatch.setattr(desktop, "browser_tabs", lambda browser: [])  # the world's browser has the one page
        monkeypatch.setattr(desktop, "show_tab", lambda browser, url: False)
        # `wait` is the one action that touches no machine call, so the only way the world hears
        # about it is the handler itself. Without this a loading page would never finish loading.
        monkeypatch.setitem(actions._HANDLERS, "wait", lambda decision, screen, items, ctx: (self.apply("wait"), "waited")[1])


def drive(
    world: World,
    policy: Policy,
    goal: str = "do the thing",
    steps: int = 20,
    monkeypatch=None,
    tmp_path=None,
    writer: FakeWriter | None = None,
    email: str | None = None,
    noul: float = 0.95,
    replies: list[str] | None = None,
    handoffs: int | None = None,
    events: Events | None = None,
    act: bool = True,
    read_only: bool = False,
    moves: bool = False,
    shortcuts: Callable[[dict], str] | None = None,
    plan: bool = False,
    permissions: str = "full",
    changes: Callable[[dict], float] | None = None,
) -> RunState:
    """Run the real loop against the world until it stops itself. `world.fake` holds the classifier.

    `replies` are what the user types when the writer asks, in order; with none, nobody is at the
    terminal and the writer is told so. `world.asked` collects the questions that were put.
    With `events`, the run reports there, as `clicker --events` does, and the replies come from it.
    """
    world.install(monkeypatch)
    fake = FakeTypeSafe(policy, noul, read_only, moves, shortcuts, plan, changes)
    world.fake = fake
    monkeypatch.setattr(runner, "DecisionClient", lambda: fake)
    cfg = RunConfig(goal=goal, out=tmp_path / "run", act=act, steps=steps, delay=0, permissions=permissions)
    if handoffs is not None:
        cfg.handoffs = handoffs
    client = writer or FakeWriter()
    left = list(replies or [])

    def ask(question: str) -> str:
        world.asked.append(question)
        return events.ask(question) if events is not None else left.pop(0) if left else ""

    return run(
        cfg,
        lambda typesafe, history: Context(
            goal=goal,
            browser="Google Chrome",
            email=email,
            typesafe=typesafe,
            writer=client,
            history=history,
            ask=ask if replies is not None or events is not None else None,
        ),
        events,
    )

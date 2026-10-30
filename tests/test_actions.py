import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from PIL import Image

from typesafe_computer_use import actions
from typesafe_computer_use.actions import click_item, fill_field, press_offscreen
from typesafe_computer_use.models import AxNode, Field, Item, Missed, Popup
from typesafe_computer_use.platform_adapter import desktop
from typesafe_computer_use.writer import Fill, make_writer


@pytest.fixture
def calls(monkeypatch):
    """Every trip to the machine, recorded instead of made."""
    log: list[tuple] = []
    monkeypatch.setattr(desktop, "click_at", lambda point: log.append(("click", point)))
    monkeypatch.setattr(desktop, "type_text", lambda text: log.append(("type", text)))
    monkeypatch.setattr(desktop, "ax_focus", lambda ref: log.append(("focus", ref)) or True)
    monkeypatch.setattr(desktop, "clear_field", lambda: log.append(("clear",)))
    return log


def field(ref=None, value="") -> Field:
    return Field(role="AXTextField", label="Email", placeholder="", value=value, x=10, y=20, w=200, h=30, ref=ref)


def test_an_item_from_the_accessibility_tree_is_pressed(screen, calls, monkeypatch):
    ref = object()
    pressed = []
    monkeypatch.setattr(desktop, "ax_press", lambda r: pressed.append(r) or True)
    item = Item(3, "Register Now", 1.0, 100.0, 100.0, 300.0, 140.0, role="link", source="ax")
    live = replace(screen, ax_refs={3: ref})
    assert click_item(item, live) == "pressed 'Register Now' via accessibility"
    assert pressed == [ref] and calls == []


def test_a_refused_press_falls_back_to_the_mouse(screen, calls, monkeypatch):
    monkeypatch.setattr(desktop, "ax_press", lambda ref: False)
    item = Item(3, "Register Now", 1.0, 100.0, 100.0, 300.0, 140.0, role="link", source="ax")
    live = replace(screen, ax_refs={3: object()})
    assert click_item(item, live) == "clicked 'Register Now' (accessibility press did not take)"
    assert calls == [("click", (100.0, 60.0))]


REGISTER = Item(3, "Register Now", 1.0, 100.0, 100.0, 300.0, 140.0, role="link", source="ax")


@pytest.fixture
def page(screen, monkeypatch):
    """The screen of a web page whose element takes every press; `shown` is what the display shows next."""
    shown = {"image": screen.image.copy()}
    monkeypatch.setattr(desktop, "ax_press", lambda ref: True)
    monkeypatch.setattr(desktop, "sleep_watching", lambda seconds: None)
    monkeypatch.setattr(desktop, "screenshot", lambda: shown["image"])
    return replace(screen, url="https://www.google.com/travel/flights", ax_refs={3: object()}), shown


def test_a_press_on_a_web_page_that_changes_nothing_falls_back_to_the_mouse(page, calls):
    """Google Flights takes AXPress on a calendar day, says yes, and selects nothing."""
    live, _ = page
    assert click_item(REGISTER, live) == "clicked 'Register Now' (accessibility press changed nothing on screen)"
    assert calls == [("click", (100.0, 60.0))]


def test_a_press_on_a_web_page_that_shows_is_left_at_that(page, calls):
    live, shown = page
    shown["image"].paste((255, 255, 255), (900, 500, 1100, 700))
    assert click_item(REGISTER, live) == "pressed 'Register Now' via accessibility"
    assert calls == []


def test_a_blinking_caret_or_a_ticking_clock_is_not_a_press_that_showed(page, calls):
    live, shown = page
    live = replace(live, field=field())
    shown["image"].paste((255, 255, 255), (20, 40, 420, 100))  # inside the focused field, in capture pixels
    shown["image"].paste((255, 255, 255), (1700, 0, 2000, 60))  # the menu bar
    assert click_item(REGISTER, live) == "clicked 'Register Now' (accessibility press changed nothing on screen)"
    assert calls == [("click", (100.0, 60.0))]


def test_an_ocr_only_item_is_clicked_without_asking_accessibility(screen, calls, monkeypatch):
    monkeypatch.setattr(desktop, "ax_press", lambda ref: pytest.fail("no element to press"))
    item = Item(3, "Register Now", 0.9, 100.0, 100.0, 300.0, 140.0)
    assert click_item(item, screen) == "clicked 'Register Now'"
    assert calls == [("click", (100.0, 60.0))]


def test_a_click_that_could_not_be_aimed_is_refused_and_the_run_goes_on(screen, monkeypatch):
    def miss(point):
        raise Missed("the cursor went to (0, 0), not (100, 60)")

    monkeypatch.setattr(desktop, "click_at", miss)
    item = Item(3, "Register Now", 0.9, 100.0, 100.0, 300.0, 140.0)
    assert click_item(item, screen) == "click refused: 'Register Now' was not clicked, the cursor went to (0, 0), not (100, 60)"


def test_an_off_screen_control_is_pressed_through_accessibility(screen, calls, monkeypatch):
    ref = object()
    pressed = []
    monkeypatch.setattr(desktop, "ax_press", lambda r: pressed.append(r) or True)
    node = AxNode(role="AXLink", label="Register Now", x=0.0, y=-4200.0, w=120.0, h=32.0, pressable=True, ref=ref)
    live = replace(screen, offscreen=[node])
    assert press_offscreen("0", live) == "pressed 'Register Now' (off-screen control) via accessibility"
    assert pressed == [ref] and calls == []


def test_a_refused_off_screen_press_is_a_no_op_with_nothing_to_click(screen, calls, monkeypatch):
    monkeypatch.setattr(desktop, "ax_press", lambda ref: False)
    node = AxNode(role="AXLink", label="Register Now", x=0.0, y=-4200.0, w=120.0, h=32.0, pressable=True, ref=object())
    refusal = press_offscreen("0", replace(screen, offscreen=[node]))
    assert refusal == "press_offscreen refused: 'Register Now' did not accept the press"
    assert calls == []


def test_an_offscreen_key_that_names_nothing_is_refused(screen, calls, monkeypatch):
    monkeypatch.setattr(desktop, "ax_press", lambda ref: pytest.fail("no element to press"))
    refusal = press_offscreen("4", screen)
    assert refusal == "press_offscreen refused: there is no off-screen control '4'"
    assert calls == []


def test_perform_routes_an_offscreen_key_to_the_press(screen, calls, monkeypatch):
    pressed = []
    monkeypatch.setattr(desktop, "ax_press", lambda r: pressed.append(r) or True)
    ref = object()
    node = AxNode(role="AXRow", label="Note 900", x=0.0, y=42718.0, w=280.0, h=68.0, pressable=True, ref=ref)
    live = replace(screen, offscreen=[node])
    decision = SimpleNamespace(chosen="offscreen:0")
    assert actions.perform(decision, live, [], None) == "pressed 'Note 900' (off-screen control) via accessibility"
    assert pressed == [ref]


# Chrome's "Restore pages?" bubble on OSWorld's chrome/2ad9387a, in screen points, over the bookmark
# manager's Organise button, whose center is under the bubble's Close button.
CLOSE = AxNode(role="AXButton", label="Close", x=1879.0, y=128.0, w=24.0, h=22.0, pressable=False)
BUBBLE = Popup("Restore pages?", 1592.0, 103.0, 334.0, 260.0, close=CLOSE)
ORGANISE = Item(3, "Organise", 1.0, 3744.0, 252.0, 3808.0, 316.0, role="button", source="ax")  # capture pixels, scale 2


@pytest.fixture
def keys_and_pauses(monkeypatch):
    log: list[tuple] = []
    monkeypatch.setattr(desktop, "press", lambda key, command=False: log.append(("press", key)))
    monkeypatch.setattr(desktop, "sleep_watching", lambda seconds: log.append(("sleep", seconds)))
    return log


def test_an_item_under_a_popup_is_clicked_after_the_popups_close_button(screen, calls, keys_and_pauses):
    live = replace(screen, covered={3: BUBBLE})
    assert click_item(ORGANISE, live) == "closed 'Restore pages?' then clicked 'Organise'"
    assert calls == [("click", (1891.0, 139.0)), ("click", (1888.0, 142.0))]
    assert keys_and_pauses == [("sleep", actions.CLOSE_SECONDS)]


def test_a_popup_with_no_close_button_is_closed_with_escape_and_never_with_its_other_buttons(screen, calls, keys_and_pauses):
    live = replace(screen, covered={3: replace(BUBBLE, name="", close=None)})
    assert click_item(ORGANISE, live) == "closed a popup with Escape then clicked 'Organise'"
    assert calls == [("click", (1888.0, 142.0))]
    assert keys_and_pauses == [("press", "escape"), ("sleep", actions.CLOSE_SECONDS)]


def test_a_close_button_the_pointer_cannot_reach_leaves_escape(screen, keys_and_pauses, monkeypatch):
    clicks = []

    def click_at(point):
        if point == (1891.0, 139.0):
            raise Missed("the cursor went to (0, 0)")
        clicks.append(point)

    monkeypatch.setattr(desktop, "click_at", click_at)
    assert (
        click_item(ORGANISE, replace(screen, covered={3: BUBBLE}))
        == "closed 'Restore pages?' with Escape then clicked 'Organise'"
    )
    assert clicks == [(1888.0, 142.0)]


def test_an_item_pressed_through_accessibility_leaves_the_popup_alone(screen, calls, keys_and_pauses, monkeypatch):
    """A press reaches the control under a popup, so there is nothing to close."""
    monkeypatch.setattr(desktop, "ax_press", lambda ref: True)
    live = replace(screen, ax_refs={3: object()}, covered={3: BUBBLE})
    assert click_item(ORGANISE, live) == "pressed 'Organise' via accessibility"
    assert calls == [] and keys_and_pauses == []


def context(writer=None) -> actions.Context:
    return actions.Context(
        goal="find the next upcoming bruno mars concert",
        browser="Google Chrome",
        email=None,
        typesafe=None,
        writer=writer,
        history=[],
    )


def browsing(site: str, browser: str | None = None) -> SimpleNamespace:
    """A use_browser decision; `browser` is the browser answer, None when one browser asks no question."""
    chosen = SimpleNamespace(choice=browser) if browser is not None else None
    return SimpleNamespace(chosen="use_browser", site=SimpleNamespace(choice=site), browser=chosen)


@pytest.fixture
def browser(monkeypatch):
    """The trips use_browser makes, recorded, with both of them reporting success."""
    log: list[tuple] = []
    monkeypatch.setattr(desktop, "activate", lambda app: log.append(("activate", app)) or True)
    monkeypatch.setattr(desktop, "open_url", lambda app, url: log.append(("open", app, url)) or True)
    return log


def test_use_browser_with_no_site_only_brings_the_browser_forward(screen, browser):
    assert actions.perform(browsing("none"), screen, [], context()) == "activated Google Chrome"
    assert browser == [("activate", "Google Chrome")]


def test_use_browser_opens_a_catalog_site_by_its_url(screen, browser, monkeypatch):
    monkeypatch.setattr(actions, "compose_url", lambda *a: pytest.fail("the catalog already names this site"))
    assert actions.perform(browsing("github"), screen, [], context()) == "opened https://github.com/"
    assert browser == [("open", "Google Chrome", "https://github.com/")]


def test_use_browser_opens_the_site_in_the_browser_the_classifier_chose(screen, browser):
    """Asked for Brave, the run opens the page in Brave, not in the configured Chrome."""
    assert actions.perform(browsing("github", "Brave Browser"), screen, [], context()) == (
        "opened https://github.com/ in Brave Browser"
    )
    assert browser == [("open", "Brave Browser", "https://github.com/")]


def test_use_browser_with_no_site_brings_the_chosen_browser_forward(screen, browser):
    assert actions.perform(browsing("none", "Brave Browser"), screen, [], context()) == "activated Brave Browser"
    assert browser == [("activate", "Brave Browser")]


def test_use_browser_asks_the_writer_for_a_site_outside_the_catalog(screen, browser, monkeypatch):
    writer = object()
    asked = []
    monkeypatch.setattr(
        actions,
        "compose_url",
        lambda w, goal, history, guidance: asked.append((w, goal)) or "https://www.songkick.com/",
    )
    assert actions.perform(browsing("other"), screen, [], context(writer)) == "opened https://www.songkick.com/"
    assert asked == [(writer, "find the next upcoming bruno mars concert")]
    assert browser == [("open", "Google Chrome", "https://www.songkick.com/")]


def test_use_browser_without_a_writer_refuses_a_site_outside_the_catalog(screen, browser):
    refusal = actions.perform(browsing("other"), screen, [], context())
    assert refusal == "use_browser refused: the site is outside the catalog and no writer is available to propose a URL"
    assert browser == []


def test_use_browser_refuses_when_the_writer_proposes_nothing(screen, browser, monkeypatch):
    monkeypatch.setattr(actions, "compose_url", lambda writer, goal, history, guidance: "")
    refusal = actions.perform(browsing("other"), screen, [], context(object()))
    assert refusal == "use_browser refused: the writer proposed no usable URL for this goal"
    assert browser == []


@pytest.fixture
def broken_writer(clean_env, endpoint):
    """A real writer whose endpoint refuses every request."""
    clean_env.setenv("CLICKER_WRITER_BASE_URL", endpoint.url)
    endpoint.state["reject"] = lambda body: "model 'nope' not found"
    return make_writer()


def test_a_writer_that_fails_refuses_the_url_instead_of_ending_the_run(screen, browser, broken_writer):
    refusal = actions.perform(browsing("other"), screen, [], context(broken_writer))
    assert refusal.startswith("use_browser refused: the writer failed (") and "not found" in refusal
    assert browser == []


def test_a_writer_that_fails_refuses_the_text_instead_of_ending_the_run(screen, calls, broken_writer):
    focused = replace(screen, field=field())
    refusal = actions.perform(SimpleNamespace(chosen="type_text"), focused, [], context(broken_writer))
    assert refusal.startswith("type_text refused: the writer failed (") and "not found" in refusal
    assert calls == []


def test_a_browser_that_does_not_come_to_the_front_is_a_no_op(screen, monkeypatch):
    monkeypatch.setattr(desktop, "activate", lambda app: False)
    failure = actions.perform(browsing("none"), screen, [], context())
    assert failure == "use_browser failed: Google Chrome did not come to the front"


def opening(app: str | None) -> SimpleNamespace:
    """An open_app decision; `app` is the app answer."""
    return SimpleNamespace(chosen="open_app", app=SimpleNamespace(choice=app) if app is not None else None)


@pytest.fixture
def opened(monkeypatch):
    """The apps open_app brings forward, recorded, each reporting success."""
    log: list[tuple] = []
    monkeypatch.setattr(desktop, "activate", lambda app, timeout=3.0: log.append((app, timeout)) or True)
    return log


def test_open_app_brings_the_chosen_app_forward_with_time_to_start(screen, opened):
    ctx = replace(context(), apps=("Notes", "Photos"))
    assert actions.perform(opening("Photos"), screen, [], ctx) == "opened Photos"
    assert opened == [("Photos", actions.OPEN_SECONDS)]


@pytest.mark.parametrize("app", ["none", "Terminal", None])
def test_open_app_refuses_an_app_that_is_not_one_of_the_installed_ones(screen, opened, app):
    ctx = replace(context(), apps=("Notes", "Photos"))
    assert actions.perform(opening(app), screen, [], ctx) == "open_app refused: no installed app is the one the goal needs"
    assert opened == []


def test_open_app_refuses_the_app_already_in_front(screen, opened):
    ctx = replace(context(), apps=("Google Chrome", "Photos"))
    assert actions.perform(opening("Google Chrome"), screen, [], ctx) == "open_app refused: Google Chrome is already in front"
    assert opened == []


def test_an_app_that_does_not_come_to_the_front_is_a_no_op(screen, monkeypatch):
    monkeypatch.setattr(desktop, "activate", lambda app, timeout=3.0: False)
    ctx = replace(context(), apps=("Photos",))
    assert actions.perform(opening("Photos"), screen, [], ctx) == "open_app failed: Photos did not come to the front"


def test_typing_sets_the_value_when_the_field_reads_it_back(calls, monkeypatch):
    written = []
    monkeypatch.setattr(desktop, "ax_set_value", lambda ref, text: written.append(text) or True)
    monkeypatch.setattr(desktop, "ax_value", lambda ref: written[-1])
    ref = object()
    assert fill_field(field(ref=ref), "user@example.com") == "via accessibility"
    assert written == ["user@example.com"] and calls == [("focus", ref)]


def test_typing_accepts_a_read_back_that_ends_with_the_text(calls, monkeypatch):
    monkeypatch.setattr(desktop, "ax_set_value", lambda ref, text: True)
    monkeypatch.setattr(desktop, "ax_value", lambda ref: "mailto:user@example.com")
    assert fill_field(field(ref=object()), "user@example.com") == "via accessibility"
    assert ("type", "user@example.com") not in calls


def test_typing_falls_back_to_keystrokes_when_the_value_does_not_stick(calls, monkeypatch):
    monkeypatch.setattr(desktop, "ax_set_value", lambda ref, text: True)
    monkeypatch.setattr(desktop, "ax_value", lambda ref: "user@exam")  # the element took part of it and reads back the rest
    assert fill_field(field(ref=object()), "user@example.com") == "via keystrokes"
    assert calls[-2:] == [("clear",), ("type", "user@example.com")]  # emptied first, whatever the capture said the value was


def test_typing_falls_back_to_keystrokes_when_the_element_refuses(calls, monkeypatch):
    monkeypatch.setattr(desktop, "ax_set_value", lambda ref, text: False)
    monkeypatch.setattr(desktop, "ax_value", lambda ref: pytest.fail("nothing was written"))
    assert fill_field(field(ref=object()), "hello") == "via keystrokes"
    assert calls[-1] == ("type", "hello")


def test_typing_uses_keystrokes_when_there_is_no_element(calls, monkeypatch):
    monkeypatch.setattr(desktop, "ax_set_value", lambda ref, text: pytest.fail("no element to write to"))
    assert fill_field(field(), "hello") == "via keystrokes"
    assert calls == [("clear",), ("type", "hello")]


def test_the_field_record_leaves_the_element_out_so_a_run_can_be_written():
    record = field(ref=object(), value="hello").record()
    assert "ref" not in record and json.loads(json.dumps(record))["value"] == "hello"


def test_a_wait_gives_the_page_time_before_the_step_delay(monkeypatch):
    slept = []
    monkeypatch.setattr(desktop, "sleep_watching", slept.append)
    assert actions._HANDLERS["wait"](None, None, [], None) == "waited"
    assert slept == [actions.WAIT_SECONDS]


# Google Maps, in capture pixels at scale 2: the results list down the left, the map filling the rest.
LISTING = Item(5, "Angelo's Pizza Pasta and Deli 4.5", 0.9, 60.0, 1160.0, 640.0, 1200.0)
MAP_LABEL = Item(6, "Gaithersburg", 0.9, 1400.0, 600.0, 1560.0, 630.0)
APPLE_MENU = Item(0, "Apple", 1.0, 20.0, 4.0, 60.0, 40.0, role="menu", source="ax")


def scrolling(item: Item | None) -> SimpleNamespace:
    """A scroll_down decision whose item answer is `item`."""
    return SimpleNamespace(chosen="scroll_down", item=SimpleNamespace(choice=str(item.index)) if item else None)


@pytest.fixture
def wheel(screen, monkeypatch):
    """Where each scroll parked the pointer, and `shown`, what the display shows after it."""
    log: list = []
    shown = {"image": screen.image.copy()}
    monkeypatch.setattr(desktop, "scroll", lambda lines, at=None: log.append((lines, at)))
    monkeypatch.setattr(desktop, "sleep_watching", lambda seconds: None)
    monkeypatch.setattr(desktop, "screenshot", lambda: shown["image"])
    return log, shown


def test_a_scroll_goes_over_the_item_the_classifier_picked(screen, wheel):
    """Sixteen scrolls at the window's center zoomed Google Maps out to the whole East Coast while
    the results list beside it never moved. Over the listing, the list is what scrolls."""
    log, shown = wheel
    shown["image"].paste((255, 255, 255), (0, 900, 700, 1200))  # the list moved up under the pointer
    what = actions.perform(scrolling(LISTING), screen, [LISTING, MAP_LABEL], None)
    assert what == 'scrolled down over "Angelo\'s Pizza Pasta and Deli 4.5"'
    assert log == [(-10, (175.0, 590.0))]


def test_a_scroll_that_moved_nothing_under_the_pointer_says_so(screen, wheel):
    """The map repainting elsewhere is not the list moving."""
    _, shown = wheel
    shown["image"].paste((255, 255, 255), (1200, 200, 2000, 900))
    what = actions.perform(scrolling(LISTING), screen, [LISTING, MAP_LABEL], None)
    assert what == 'scrolled down over "Angelo\'s Pizza Pasta and Deli 4.5" (nothing there moved)'


@pytest.mark.parametrize(
    "item, window",
    [
        (None, None),  # no item question: nothing on screen was read
        (APPLE_MENU, None),  # a wheel over the menu bar reaches no app
        (MAP_LABEL, (0.0, 30.0, 500.0, 570.0)),  # outside the frontmost window
    ],
)
def test_a_scroll_with_no_item_to_aim_at_goes_to_the_window_center(screen, wheel, item, window):
    log, shown = wheel
    shown["image"].paste((255, 255, 255), (900, 500, 1100, 700))
    what = actions.perform(scrolling(item), replace(screen, window=window), [APPLE_MENU, LISTING, MAP_LABEL], None)
    assert what == "scrolled down"
    assert log == [(-10, None)]


def test_a_scroll_at_the_window_center_that_changed_nothing_says_so(screen, wheel):
    what = actions.perform(scrolling(None), screen, [], None)
    assert what == "scrolled down (nothing there moved)"


def test_clicking_a_duplicated_label_says_which_row(screen, calls):
    items = [
        Item(0, "Coldplay", 1.0, 100, 200, 300, 230),
        Item(1, "Buy", 1.0, 420, 200, 480, 230),
        Item(2, "Adele", 1.0, 100, 260, 300, 290),
        Item(3, "Buy", 1.0, 420, 260, 480, 290),
        Item(4, "Terms", 1.0, 100, 320, 300, 350),
    ]

    def clicking(key: str):
        return SimpleNamespace(chosen=key)

    assert actions.perform(clicking("3"), screen, items, None) == "clicked 'Buy' beside 'Adele'"
    assert actions.perform(clicking("4"), screen, items, None) == "clicked 'Terms'"
    assert [point for kind, point in calls if kind == "click"] == [(225.0, 137.5), (100.0, 167.5)]


def test_failed_verification_restores_original_field_without_touching_new_focus(screen, monkeypatch):
    original = field(ref=object(), value="previous query")
    other = field(ref=object(), value="important draft")
    values = {original.ref: "new query", other.ref: other.value}
    monkeypatch.setattr(actions, "compose_text", lambda *a: Fill("new query"))
    monkeypatch.setattr(actions, "fill_field", lambda *a: "via accessibility")
    monkeypatch.setattr(actions.time, "sleep", lambda *a: None)
    monkeypatch.setattr(desktop, "focused_field", lambda pid=None: other)
    monkeypatch.setattr(actions, "verify_typed", lambda *a: 0.0)
    monkeypatch.setattr(desktop, "ax_value", values.get)
    monkeypatch.setattr(desktop, "ax_set_value", lambda ref, text: values.__setitem__(ref, text) or True)
    monkeypatch.setattr(desktop, "clear_field", lambda: pytest.fail("must not clear the current focus"))

    result = actions._type_text(None, replace(screen, field=original), [], context(object()))

    assert "restored previous value" in result
    assert values == {original.ref: original.value, other.ref: other.value}


def test_a_stand_in_field_is_read_back_from_its_row_of_the_screen_left_to_right(monkeypatch):
    """One box height above and below, across the whole display: the clicked text may be a label at
    one end of the input and the value at the other."""
    crops = []
    monkeypatch.setattr(desktop, "screenshot", lambda: Image.new("RGB", (2000, 1200)))
    monkeypatch.setattr(desktop, "display_scale", lambda image: 2.0)

    def recognize_text(image):
        crops.append(image.size)
        return [("0.29", 0.9, (900.0, 4.0, 960.0, 30.0)), ("Amount", 0.9, (100.0, 4.0, 200.0, 30.0))]

    monkeypatch.setattr(desktop, "recognize_text", recognize_text)
    box = Field(role="", label="Amount", placeholder="", value="", x=50, y=300, w=60, h=15, clicked=True)
    assert actions.read_back(box).value == "Amount | 0.29"
    assert crops == [(2000, 90)]  # points 285 to 330, at scale 2


def test_text_typed_into_a_stand_in_field_is_checked_against_the_screen(screen, calls, monkeypatch):
    box = Field(role="", label="10", placeholder="", value="", x=500, y=300, w=20, h=16, clicked=True)
    checked = []
    monkeypatch.setattr(desktop, "ax_set_value", lambda *a: pytest.fail("a stand-in has no element"))
    monkeypatch.setattr(desktop, "focused_field", lambda pid=None: pytest.fail("the browser reports no focus"))
    monkeypatch.setattr(actions, "compose_text", lambda *a: Fill("0.29"))
    monkeypatch.setattr(actions.time, "sleep", lambda *a: None)
    monkeypatch.setattr(actions, "read_back", lambda f: replace(f, value="Amount | 0.29"))
    monkeypatch.setattr(actions, "verify_typed", lambda client, goal, before, text, after: checked.append(after.value) or 0.9)

    result = actions._type_text(None, replace(screen, field=box), [], context(object()))

    assert result == "typed '0.29' into '10' via keystrokes (verified 0.90)"
    assert calls == [("clear",), ("type", "0.29")]
    assert checked == ["Amount | 0.29"]


# Google Docs takes its keys in a hidden box: a bare, untitled AXGroup one point tall.
DOC = Field(role="AXGroup", label="", placeholder="", value="", x=0, y=114, w=625, h=1, ref=object(), editor=True)


def test_an_editor_takes_text_at_its_caret_and_is_never_emptied_or_overwritten(calls, monkeypatch):
    """Select All and Delete in a document wipe the document."""
    monkeypatch.setattr(desktop, "ax_set_value", lambda *a: pytest.fail("a value would replace the document"))
    assert fill_field(DOC, "Flights to Barcelona") == "at the caret via keystrokes"
    assert calls == [("type", "Flights to Barcelona")]


def test_an_editor_is_read_back_from_the_screen_lines_that_share_a_word_with_the_typing(monkeypatch):
    monkeypatch.setattr(desktop, "screenshot", lambda: Image.new("RGB", (2000, 1200)))
    lines = [
        ("$695 round trip, TAP Air Portugal", 0.9, (300.0, 420.0, 900.0, 450.0)),
        ("Untitled document", 0.9, (100.0, 80.0, 400.0, 110.0)),
        ("Cheapest flight to Barcelona", 0.9, (300.0, 380.0, 900.0, 410.0)),
    ]
    monkeypatch.setattr(desktop, "recognize_text", lambda image: lines)
    typed = "Cheapest flight to Barcelona\n$695 round trip, TAP Air Portugal"
    assert actions.read_editor(DOC, typed).value == "Cheapest flight to Barcelona | $695 round trip, TAP Air Portugal"


def test_text_typed_into_an_editor_is_checked_against_the_screen(screen, calls, monkeypatch):
    checked = []
    monkeypatch.setattr(actions, "compose_text", lambda *a: Fill("Cheapest flight: $695"))
    monkeypatch.setattr(actions.time, "sleep", lambda *a: None)
    monkeypatch.setattr(desktop, "focused_field", lambda pid=None: pytest.fail("the editor's box holds none of the document"))
    monkeypatch.setattr(actions, "read_editor", lambda f, text: replace(f, value="Cheapest flight: $695"))
    monkeypatch.setattr(actions, "verify_typed", lambda client, goal, before, text, after: checked.append(after.value) or 0.9)

    result = actions._type_text(None, replace(screen, field=DOC), [], context(object()))

    assert result == "typed 'Cheapest flight: $695' into '' at the caret via keystrokes (verified 0.90)"
    assert calls == [("type", "Cheapest flight: $695")]
    assert checked == ["Cheapest flight: $695"]


def test_an_editor_is_a_multiline_text_field_that_tells_the_classifier_what_it_is():
    assert DOC.is_text and DOC.multiline
    assert "caret" in DOC.summary()["note"]
    assert not replace(DOC, editor=False).is_text and "note" not in field().summary()


def test_text_the_writer_submits_is_followed_by_return_and_left_to_the_next_screen(screen, calls, monkeypatch):
    """Return usually takes the field away, so nothing reads it afterwards and nothing is restored."""
    monkeypatch.setattr(desktop, "press", lambda key, command=False: calls.append(("press", key)))
    monkeypatch.setattr(actions, "compose_text", lambda *a: Fill("Favorites", submit=True))
    monkeypatch.setattr(actions.time, "sleep", lambda *a: pytest.fail("there is no read to wait for"))
    monkeypatch.setattr(desktop, "focused_field", lambda pid=None: pytest.fail("the field is gone after Return"))
    monkeypatch.setattr(actions, "verify_typed", lambda *a: pytest.fail("nothing to check the text against"))
    monkeypatch.setattr(actions, "restore_field", lambda *a: pytest.fail("nothing to restore"))

    result = actions._type_text(None, replace(screen, field=field()), [], context(object()))

    assert result == "typed 'Favorites' into 'Email' via keystrokes and pressed Return"
    assert calls == [("clear",), ("type", "Favorites"), ("press", "return")]


@pytest.mark.parametrize("current", [None, "user edited the value", "prefix new query"])
def test_recovery_leaves_a_missing_or_changed_original_field_alone(current, monkeypatch):
    monkeypatch.setattr(desktop, "ax_value", lambda ref: current)
    monkeypatch.setattr(desktop, "ax_set_value", lambda *a: pytest.fail("not our value anymore"))
    assert not actions.restore_field(field(ref=object()), "new query")


def test_recovery_without_a_handle_never_uses_keyboard_input(monkeypatch):
    monkeypatch.setattr(desktop, "clear_field", lambda: pytest.fail("unknown target"))
    monkeypatch.setattr(desktop, "type_text", lambda *a: pytest.fail("unknown target"))
    assert not actions.restore_field(field(), "new query")


def test_refused_restore_has_no_keyboard_fallback(monkeypatch):
    monkeypatch.setattr(desktop, "ax_value", lambda ref: "new query")
    monkeypatch.setattr(desktop, "ax_set_value", lambda *a: False)
    monkeypatch.setattr(desktop, "clear_field", lambda: pytest.fail("must not clear the current focus"))
    assert not actions.restore_field(field(ref=object()), "new query")

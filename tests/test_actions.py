import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from PIL import Image

from typesafe_computer_use import actions, perception
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


@pytest.fixture
def pointer(monkeypatch):
    """Every pointer click the desktop was asked for, with its button and how many times."""
    log: list[tuple] = []
    monkeypatch.setattr(desktop, "click_at", lambda point, button="left", count=1: log.append((point, button, count)))
    return log


def pointing(kind: str, index: int | None) -> SimpleNamespace:
    item = SimpleNamespace(choice=str(index)) if index is not None else None
    return SimpleNamespace(chosen=kind, kind=SimpleNamespace(choice=kind), item=item)


@pytest.mark.parametrize(
    "kind, said, button, count",
    [
        ("right_click_item", "right-clicked 'Organise'", "right", 1),
        ("double_click_item", "double-clicked 'Organise'", "left", 2),
        ("select_item_text", "selected the text of 'Organise'", "left", 3),
    ],
)
def test_the_other_clicks_are_pointer_clicks_even_on_a_control_the_tree_could_press(screen, pointer, kind, said, button, count):
    row = replace(ORGANISE, role="cell")  # a list row the tree could press; a double click opens it
    live = replace(screen, ax_refs={3: object()})  # a press would be a single left click, so none is made
    assert actions.perform(pointing(kind, 3), live, [row], context()) == said
    assert pointer == [((1888.0, 142.0), button, count)]


@pytest.mark.parametrize("kind", ["double_click_item", "select_item_text"])
@pytest.mark.parametrize("role", ["button", "link", "checkbox", "radio", "popup", "menu", "tab"])
def test_a_second_click_is_refused_on_a_control_that_one_click_activates(screen, pointer, kind, role):
    control = replace(ORGANISE, role=role)
    said = actions.perform(pointing(kind, 3), screen, [control], context())
    assert said == f"{kind} refused: 'Organise' is a {role}, one click activates it"
    assert pointer == []


@pytest.mark.parametrize(
    "ax_role, word",
    [("AXMenuItem", "menu item"), ("AXDisclosureTriangle", "disclosure"), ("AXButton", "button"), ("AXLink", "link")],
)
@pytest.mark.parametrize("kind", ["double_click_item", "select_item_text"])
def test_a_second_click_is_refused_on_what_the_tree_calls_a_menu_entry_or_a_disclosure_triangle(
    screen, pointer, ax_role, word, kind
):
    """Through the role mapping, not with a role word written into the item: a gap in the map would show here."""
    node = AxNode(role=ax_role, label="Copy", x=1888.0 / 2 - 20, y=142.0 / 2 - 8, w=40.0, h=16.0, pressable=True)
    (item,) = perception.to_ax_items([node], 2.0)
    assert item.role == word
    said = actions.perform(pointing(kind, 0), screen, [item], context())
    assert said == f"{kind} refused: 'Copy' is a {word}, one click activates it"
    assert pointer == []


def test_a_right_click_is_fine_on_a_button(screen, pointer):
    assert actions.perform(pointing("right_click_item", 3), screen, [ORGANISE], context()) == "right-clicked 'Organise'"
    assert pointer == [((1888.0, 142.0), "right", 1)]


def test_the_other_clicks_name_the_row_when_a_label_repeats(screen, pointer):
    buy = [
        Item(0, "Buy", 1.0, 3000.0, 100.0, 3100.0, 130.0),
        Item(1, "Mars", 1.0, 100.0, 100.0, 300.0, 130.0),
        Item(2, "Buy", 1.0, 3000.0, 500.0, 3100.0, 530.0),
    ]
    assert actions.perform(pointing("double_click_item", 0), screen, buy, context()) == "double-clicked 'Buy' beside 'Mars'"


def test_the_other_clicks_close_the_popup_in_front_of_the_item_first(screen, pointer, keys_and_pauses):
    live = replace(screen, covered={3: BUBBLE})
    said = actions.perform(pointing("right_click_item", 3), live, [ORGANISE], context())
    assert said.startswith("closed ") and said.endswith(" then right-clicked 'Organise'")
    assert pointer[-1][1:] == ("right", 1)


@pytest.mark.parametrize("index", [None, 9])
def test_the_other_clicks_refuse_when_no_item_on_screen_was_chosen(screen, pointer, index):
    assert actions.perform(pointing("select_item_text", index), screen, [ORGANISE], context()) == (
        "select_item_text refused: no item on screen was chosen"
    )
    assert pointer == []


def test_a_pointer_that_never_got_there_clicks_nothing_and_says_so(screen, monkeypatch):
    def miss(point, button="left", count=1):
        raise Missed("the cursor went to (0, 0)")

    monkeypatch.setattr(desktop, "click_at", miss)
    said = actions.perform(pointing("right_click_item", 3), screen, [ORGANISE], context())
    assert said == "right_click_item refused: 'Organise' was not clicked, the cursor went to (0, 0)"


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
    monkeypatch.setattr(desktop, "browser_tabs", lambda app: [])
    monkeypatch.setattr(desktop, "show_tab", lambda app, url: log.append(("show", app, url)) or True)
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
        lambda w, goal, history, guidance, tabs: asked.append((w, goal)) or "https://www.songkick.com/",
    )
    assert actions.perform(browsing("other"), screen, [], context(writer)) == "opened https://www.songkick.com/"
    assert asked == [(writer, "find the next upcoming bruno mars concert")]
    assert browser == [("open", "Google Chrome", "https://www.songkick.com/")]


def test_use_browser_without_a_writer_refuses_a_site_outside_the_catalog(screen, browser):
    refusal = actions.perform(browsing("other"), screen, [], context())
    assert refusal == "use_browser refused: the site is outside the catalog and no writer is available to propose a URL"
    assert browser == []


def test_use_browser_refuses_when_the_writer_proposes_nothing(screen, browser, monkeypatch):
    monkeypatch.setattr(actions, "compose_url", lambda writer, goal, history, guidance, tabs: "")
    refusal = actions.perform(browsing("other"), screen, [], context(object()))
    assert refusal == "use_browser refused: the writer proposed no usable URL for this goal"
    assert browser == []


GUIDE = "https://docs.google.com/document/d/abc/edit"
OPEN_TABS = [("kydno/Golf-Party issue 69", "https://github.com/kydno/Golf-Party/issues/69"), ("Ch. 10 Reading Guide", GUIDE)]


def test_use_browser_switches_to_the_open_tab_the_writer_names(screen, browser, monkeypatch):
    """The page the goal is about is open behind another tab: the writer reads the tabs, names it,
    and the run shows that tab instead of opening the page a second time."""
    monkeypatch.setattr(desktop, "browser_tabs", lambda app: OPEN_TABS)
    read = []
    monkeypatch.setattr(actions, "compose_url", lambda w, goal, history, guidance, tabs: read.append(tabs) or GUIDE)
    assert actions.perform(browsing("other"), screen, [], context(object())) == f"switched to the open tab {GUIDE}"
    assert read == [OPEN_TABS]
    assert browser == [("show", "Google Chrome", GUIDE)]


def test_use_browser_opens_a_url_that_is_not_an_open_tab(screen, browser, monkeypatch):
    monkeypatch.setattr(desktop, "browser_tabs", lambda app: OPEN_TABS)
    monkeypatch.setattr(actions, "compose_url", lambda *a: "https://www.songkick.com/")
    assert actions.perform(browsing("other"), screen, [], context(object())) == "opened https://www.songkick.com/"
    assert browser == [("open", "Google Chrome", "https://www.songkick.com/")]


def test_use_browser_opens_the_url_when_the_tab_cannot_be_shown(screen, browser, monkeypatch):
    """The tab closed between the read and the switch: the page opens by its address instead."""
    monkeypatch.setattr(desktop, "browser_tabs", lambda app: OPEN_TABS)
    monkeypatch.setattr(desktop, "show_tab", lambda app, url: browser.append(("show", app, url)) and False)
    monkeypatch.setattr(actions, "compose_url", lambda *a: GUIDE)
    assert actions.perform(browsing("other"), screen, [], context(object())) == f"opened {GUIDE}"
    assert browser == [("show", "Google Chrome", GUIDE), ("open", "Google Chrome", GUIDE)]


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
    assert (
        actions.perform(opening("Photos"), screen, [], ctx) == "open_app failed: Photos did not come to the front with a window"
    )


def shortcut_of(name: str | None) -> SimpleNamespace:
    return SimpleNamespace(chosen="press_shortcut", shortcut=SimpleNamespace(choice=name) if name is not None else None)


@pytest.fixture
def pressed(monkeypatch):
    """Every key press the desktop was asked for, with the modifiers it carried."""
    log: list[tuple] = []
    monkeypatch.setattr(
        desktop,
        "press",
        lambda key, command=False, shift=False, option=False, control=False: log.append((key, command, shift, option, control)),
    )
    return log


@pytest.mark.parametrize(
    "name, said, keys",
    [
        ("copy", "pressed the copy shortcut", ("c", True, False, False, False)),
        ("select_all", "pressed the select all shortcut", ("a", True, False, False, False)),
        ("redo", "pressed the redo shortcut", ("z", True, True, False, False)),
        ("next_tab", "pressed the next tab shortcut", ("tab", False, False, False, True)),
        ("previous_tab", "pressed the previous tab shortcut", ("tab", False, True, False, True)),
        ("zoom_in", "pressed the zoom in shortcut", ("=", True, False, False, False)),
    ],
)
def test_a_shortcut_from_the_catalog_is_pressed_with_its_modifiers(screen, pressed, name, said, keys):
    assert actions.perform(shortcut_of(name), screen, [], context()) == said
    assert pressed == [keys]


@pytest.mark.parametrize("name", ["new_tab", "close_tab", "next_tab", "previous_tab", "reload"])
@pytest.mark.parametrize("app", ["Notes", "Mail", "TextEdit", ""])
def test_a_browser_shortcut_is_refused_when_another_app_is_in_front(screen, pressed, name, app):
    out = actions.perform(shortcut_of(name), replace(screen, app=app), [], context())
    assert out == f"press_shortcut refused: {name.replace('_', ' ')} works in a browser, and {app or 'no app'} is in front"
    assert pressed == []


@pytest.mark.parametrize("app", ["Google Chrome", "Safari", "Firefox", "Arc"])
def test_a_browser_shortcut_is_pressed_in_a_browser(screen, pressed, app):
    assert actions.perform(shortcut_of("close_tab"), replace(screen, app=app), [], context()) == "pressed the close tab shortcut"
    assert pressed == [("w", True, False, False, False)]


def test_the_configured_browser_counts_as_a_browser_whatever_its_name(screen, pressed):
    ctx = replace(context(), browser="Vivaldi")
    assert actions.perform(shortcut_of("reload"), replace(screen, app="Vivaldi"), [], ctx) == "pressed the reload shortcut"


@pytest.mark.parametrize("name", ["paste", "cut"])
@pytest.mark.parametrize(
    "role, label, placeholder",
    [
        ("AXSecureTextField", "", ""),
        ("AXTextField", "Password", ""),
        ("AXTextField", "", "Card number"),
        ("AXTextField", "One-time code", ""),
        ("AXTextField", "Login", "Password"),  # an innocent label does not hide a placeholder that is not
    ],
)
def test_paste_and_cut_are_refused_in_a_field_that_looks_like_a_credential(screen, pressed, name, role, label, placeholder):
    box = Field(role=role, label=label, placeholder=placeholder, value="", x=0, y=0, w=10, h=10)
    out = actions.perform(shortcut_of(name), replace(screen, field=box), [], context())
    assert out == f"press_shortcut refused: {name} would act on a field that looks like a credential"
    assert pressed == []


def test_copy_and_the_other_shortcuts_are_not_held_back_by_a_credential_field(screen, pressed):
    box = Field(role="AXSecureTextField", label="Password", placeholder="", value="", x=0, y=0, w=10, h=10)
    assert (
        actions.perform(shortcut_of("select_all"), replace(screen, field=box), [], context()) == "pressed the select all shortcut"
    )


def test_paste_goes_into_an_ordinary_field(screen, pressed):
    box = Field(role="AXTextField", label="Search", placeholder="", value="", x=0, y=0, w=10, h=10)
    assert actions.perform(shortcut_of("paste"), replace(screen, field=box), [], context()) == "pressed the paste shortcut"
    assert pressed == [("v", True, False, False, False)]


@pytest.mark.parametrize("name", ["none", "quit", "force_quit", "Cmd-Q", None])
def test_a_shortcut_outside_the_catalog_is_refused_and_presses_nothing(screen, pressed, name):
    assert actions.perform(shortcut_of(name), screen, [], context()) == (
        "press_shortcut refused: no shortcut in the list is the one the goal needs"
    )
    assert pressed == []


def test_nothing_in_the_catalog_quits_logs_out_or_types():
    from typesafe_computer_use.config import SHORTCUTS

    assert not {"q", "delete", "return", "escape"} & {s.key for s in SHORTCUTS.values()}
    assert not any(s.command and s.option and s.key == "escape" for s in SHORTCUTS.values())  # force quit
    assert all(len(s.key) == 1 or s.key == "tab" for s in SHORTCUTS.values())


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
    """Where each hover and scroll parked the pointer, and `shown`: what the display shows with the
    pointer parked ("hovered") and after the scroll ("image")."""
    log: list = []
    shown = {"image": screen.image.copy(), "hovered": screen.image.copy(), "next": "image"}

    def hover(at):
        log.append(("hover", at))
        shown["next"] = "hovered"

    def screenshot():
        which, shown["next"] = shown["next"], "image"
        return shown[which]

    monkeypatch.setattr(desktop, "hover", hover)
    monkeypatch.setattr(desktop, "scroll", lambda lines, at=None: log.append((lines, at)))
    monkeypatch.setattr(desktop, "sleep_watching", lambda seconds: None)
    monkeypatch.setattr(desktop, "screenshot", screenshot)
    return log, shown


def test_a_scroll_goes_over_the_item_the_classifier_picked(screen, wheel):
    """Sixteen scrolls at the window's center zoomed Google Maps out to the whole East Coast while
    the results list beside it never moved. Over the listing, the list is what scrolls."""
    log, shown = wheel
    shown["image"].paste((255, 255, 255), (0, 900, 700, 1200))  # the list moved up under the pointer
    what = actions.perform(scrolling(LISTING), screen, [LISTING, MAP_LABEL], None)
    assert what == 'scrolled down over "Angelo\'s Pizza Pasta and Deli 4.5"'
    assert log == [("hover", (175.0, 590.0)), (-10, (175.0, 590.0))]


def test_a_menu_the_pointer_opened_is_not_a_scroll(screen, wheel):
    """Aimed at a sidebar's 'Analytics' link on the Firebase console, the pointer opened the link's
    flyout menu and the page never moved. The menu was there before the wheel turned, so it is
    not what the scroll showed."""
    _, shown = wheel
    shown["hovered"].paste((255, 255, 255), (0, 900, 700, 1200))  # the flyout, open once the pointer is there
    shown["image"] = shown["hovered"].copy()  # and still open, with nothing scrolled, after the wheel
    what = actions.perform(scrolling(LISTING), screen, [LISTING, MAP_LABEL], None)
    assert what == 'scrolled down over "Angelo\'s Pizza Pasta and Deli 4.5" (nothing there moved)'


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


def test_the_writers_scroll_to_the_bottom_stops_once_nothing_moves(screen, wheel):
    """Named by its text, the listing is where the wheel goes; at the list's end the scrolls stop."""
    log, shown = wheel
    shown["image"].paste((255, 255, 255), (0, 900, 700, 1200))  # every scroll leaves the same screen: one moved
    what = actions.writer_scroll("bottom", "Angelo's Pizza Pasta and Deli 4.5", screen, [LISTING, MAP_LABEL])
    assert what == 'scrolled to the bottom over "Angelo\'s Pizza Pasta and Deli 4.5" (1 scroll)'
    assert log == [("hover", (175.0, 590.0)), (-10, (175.0, 590.0)), (-10, (175.0, 590.0))]


def test_the_writers_scroll_over_nothing_on_screen_goes_to_the_window_center(screen, wheel):
    log, _ = wheel
    assert actions.writer_scroll("up", "Google Analytics", screen, [LISTING, MAP_LABEL]) == "scrolled up (nothing there moved)"
    assert log == [(10, None)]


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


# The same Google Doc once Chrome has put the page in accessibility: its whole body is one text area.
DOC_BODY = Field(
    role="AXTextArea",
    label="Document content",
    placeholder="",
    value="Chapter 10 Reading Guide\nReading Schedule\n1. Describe the two key differences between interest groups and political parties.\n",
    x=280,
    y=250,
    w=1200,
    h=900,
    ref=object(),
)


def test_a_text_area_holding_a_document_takes_text_at_its_caret_and_is_never_emptied_or_overwritten(calls, monkeypatch):
    """Answering question 1 in a Google Doc replaced the whole document with the answer."""
    monkeypatch.setattr(desktop, "ax_set_value", lambda *a: pytest.fail("a value would replace the document"))
    assert fill_field(DOC_BODY, "Interest groups and political parties differ") == "at the caret via keystrokes"
    assert calls == [("type", "Interest groups and political parties differ")]


def test_a_text_area_is_checked_where_the_typing_landed_not_at_the_top_of_the_document(screen, calls, monkeypatch):
    monkeypatch.setattr(actions, "compose_text", lambda *a: Fill("Parties run candidates."))
    monkeypatch.setattr(actions.time, "sleep", lambda *a: None)
    after = replace(DOC_BODY, value="x" * 2000 + "Parties run candidates." + "y" * 2000)
    monkeypatch.setattr(desktop, "focused_field", lambda pid=None: after)
    seen = []

    class Client:
        def system_one(self, state, questions):
            seen.append(state)
            return SimpleNamespace(answers={"ok": SimpleNamespace(noul=0.9)})

    result = actions._type_text(None, replace(screen, field=DOC_BODY), [], replace(context(object()), typesafe=Client()))

    assert result == "typed 'Parties run candidates.' into 'Document content' at the caret via keystrokes (verified 0.90)"
    assert calls == [("type", "Parties run candidates.")]
    assert "Parties run candidates." in seen[0]["field_value_now"]


QUESTION = "1. Describe the two key differences between interest groups and political parties."
GUIDE_TEXT = f"Chapter 10 Reading Guide\n{QUESTION}\n2. In one sentence, summarize pluralist theory.\n"
MID_QUESTION = GUIDE_TEXT.index("between")  # where the click on the question left the caret
QUESTION_END = GUIDE_TEXT.index("\n2.")


@pytest.fixture
def keys(monkeypatch):
    """The keys pressed and where the caret ends up: each Right press moves it one character."""
    state = {"caret": MID_QUESTION, "pressed": []}

    def press(key, command=False, shift=False):
        state["pressed"].append(("shift+" if shift else "") + key)
        if key == "right":
            state["caret"] += 1

    monkeypatch.setattr(desktop, "press", press)
    monkeypatch.setattr(desktop, "sleep_watching", lambda seconds: None)
    monkeypatch.setattr(desktop, "focused_field", lambda pid=None: replace(DOC_BODY, value=GUIDE_TEXT, caret=state["caret"]))
    return state


def test_a_caret_inside_a_question_walks_to_its_end_and_the_answer_starts_a_line_of_its_own(keys):
    """Answering question 1 typed the answer into the middle of the question."""
    assert actions.make_line(replace(DOC_BODY, value=GUIDE_TEXT, caret=MID_QUESTION), 7) is True
    assert keys["pressed"] == ["right"] * (QUESTION_END - MID_QUESTION) + ["shift+return"]  # Return would renumber the list


def test_a_caret_on_a_blank_line_or_in_an_empty_field_types_where_it_is(keys):
    blank = "Question 1\n\nQuestion 2"
    assert actions.make_line(replace(DOC_BODY, value=blank, caret=blank.index("\n") + 1), 7) is False
    assert actions.make_line(replace(DOC_BODY, value="", caret=0), 7) is False
    assert actions.make_line(replace(DOC_BODY, value=GUIDE_TEXT, caret=None), 7) is False  # no caret reported
    assert keys["pressed"] == []


def test_a_caret_that_does_not_reach_the_paragraph_end_types_nothing(screen, calls, keys, monkeypatch):
    monkeypatch.setattr(
        desktop, "focused_field", lambda pid=None: replace(DOC_BODY, value=GUIDE_TEXT, caret=MID_QUESTION)
    )  # the arrows went somewhere else
    monkeypatch.setattr(actions, "compose_text", lambda *a: Fill("Parties run candidates."))
    field_in_text = replace(DOC_BODY, value=GUIDE_TEXT, caret=MID_QUESTION)

    result = actions._type_text(None, replace(screen, field=field_in_text), [], context(object()))

    assert result == "type_text refused: the caret is inside text and could not be moved to the end of its paragraph"
    assert "shift+return" not in keys["pressed"] and not any(call[0] == "type" for call in calls)


def test_the_answer_is_typed_on_its_new_line(screen, calls, keys, monkeypatch):
    monkeypatch.setattr(actions, "compose_text", lambda *a: Fill("Parties run candidates."))
    monkeypatch.setattr(actions, "verify_typed", lambda *a: 0.9)
    monkeypatch.setattr(actions.time, "sleep", lambda *a: None)
    field_in_text = replace(DOC_BODY, value=GUIDE_TEXT, caret=MID_QUESTION)

    result = actions._type_text(None, replace(screen, field=field_in_text), [], context(object()))

    assert (
        result
        == "typed 'Parties run candidates.' into 'Document content' on a new line at the caret via keystrokes (verified 0.90)"
    )
    assert keys["pressed"][-1] == "shift+return" and calls == [("type", "Parties run candidates.")]


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

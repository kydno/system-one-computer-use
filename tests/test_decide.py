from dataclasses import replace
from types import SimpleNamespace

from typesafe_computer_use.config import SITES
from typesafe_computer_use.decide import (
    Decision,
    app_criteria,
    base_state,
    browser_criteria,
    decide,
    item_criteria,
    kind_criteria,
    offscreen_criteria,
    row_mates,
    site_criteria,
    verify_typed,
)
from typesafe_computer_use.models import AxNode, Field, Guidance


def answer(choice, confidence, probabilities=None):
    return SimpleNamespace(choice=choice, confidence=confidence, probabilities=probabilities or {choice: confidence})


def test_decision_click_uses_item_and_min_confidence():
    d = Decision(kind=answer("click_item", 0.9), item=answer("12", 0.6), site=answer("none", 1.0))
    assert d.clicking and d.chosen == "12" and d.confidence == 0.6 and not d.stops


def test_decision_fixed_action_ignores_item():
    d = Decision(kind=answer("use_browser", 0.8), item=answer("3", 0.1), site=answer("github", 0.9))
    assert not d.clicking and d.chosen == "use_browser" and d.confidence == 0.8


def test_decision_use_browser_ignores_a_split_site_answer():
    d = Decision(kind=answer("use_browser", 0.88), item=None, site=answer("other", 0.45))
    assert d.chosen == "use_browser" and d.confidence == 0.88


def test_decision_stops_on_done_or_none():
    assert Decision(kind=answer("done", 0.9), item=None, site=answer("none", 1)).stops
    assert Decision(kind=answer("none", 0.9), item=None, site=answer("none", 1)).stops


def test_decision_press_offscreen_uses_the_offscreen_answer_and_min_confidence():
    d = Decision(kind=answer("press_offscreen", 0.9), item=answer("3", 0.9), site=answer("none", 1.0), offscreen=answer("7", 0.5))
    assert d.pressing_offscreen and not d.clicking and d.chosen == "offscreen:7" and d.confidence == 0.5


def test_decision_ignores_an_offscreen_answer_for_any_other_kind():
    d = Decision(kind=answer("click_item", 0.9), item=answer("3", 0.8), site=answer("none", 1.0), offscreen=answer("7", 0.1))
    assert not d.pressing_offscreen and d.chosen == "3" and d.confidence == 0.8


def test_kind_criteria_offers_press_offscreen_only_when_there_are_offscreen_controls():
    assert "press_offscreen" not in kind_criteria("Google Chrome", None)
    assert "press_offscreen" in kind_criteria("Google Chrome", None, offscreen=True)


def test_offscreen_criteria_and_state_name_the_role_and_say_it_is_not_visible(screen, make_item):
    nodes = [
        AxNode(role="AXLink", label="Register Now", x=0.0, y=-4200.0, w=120.0, h=32.0, pressable=True),
        AxNode(role="AXRow", label="Note 900", x=0.0, y=42718.0, w=280.0, h=68.0, pressable=True),
    ]
    assert offscreen_criteria(nodes) == {
        "0": "link 'Register Now' (not visible)",
        "1": "cell 'Note 900' (not visible)",
    }
    live = replace(screen, offscreen=nodes)
    state = base_state("buy the thing", live, [make_item(0, "Buy")], [])
    assert state["offscreen_controls"] == [
        {"k": 0, "role": "link", "label": "Register Now"},
        {"k": 1, "role": "cell", "label": "Note 900"},
    ]
    assert "offscreen_controls" not in base_state("buy the thing", screen, [make_item(0, "Buy")], [])


def test_kind_criteria_offers_one_browser_action():
    crit = kind_criteria("Google Chrome", None)
    assert "use_browser" in crit
    assert "switch_to_browser" not in crit and "open_site" not in crit
    assert "Google Chrome" in crit["use_browser"] and "address bar" in crit["use_browser"]


def test_site_criteria_covers_the_catalog_a_site_outside_it_and_no_site():
    crit = site_criteria()
    assert crit["github"] == SITES["github"]
    assert "not one of the sites named in this list" in crit["other"]
    assert "already open" in crit["none"]


def test_kind_criteria_offers_email_only_when_set():
    assert "type_email" not in kind_criteria("Google Chrome", None)
    assert "type_email" in kind_criteria("Google Chrome", "user@example.com")
    assert "click_item" in kind_criteria("Google Chrome", None)


def test_item_criteria_and_state_carry_region_and_dates(screen, make_item):
    items = [make_item(0, "Sale ends Oct 1, 2099", y1=100, y2=130), make_item(1, "Buy", y1=140, y2=170)]
    crit = item_criteria(screen, items)
    assert crit["0"].startswith("'Sale ends Oct 1, 2099' (top-left; dated 2099-10-01")
    assert "near a line dated 2099-10-01" in crit["1"]
    state = base_state("buy the thing", screen, items, ["opened https://example.com/"])
    assert state["goal"] == "buy the thing"
    assert state["previous_actions"] == ["opened https://example.com/"]
    assert state["screen_items_in_reading_order"][1]["when"].startswith("near a line dated")
    assert "today" in state["now"]


def test_a_duplicated_label_names_its_row_and_a_unique_one_does_not(screen, make_item):
    items = [
        make_item(0, "Bruno Mars", x1=100, x2=300),
        make_item(1, "Sep 25", x1=320, x2=400),
        make_item(2, "Buy", x1=420, x2=480),
        make_item(3, "Coldplay", x1=100, x2=300, y1=200, y2=230),
        make_item(4, "Oct 2", x1=320, x2=400, y1=200, y2=230),
        make_item(5, "Buy", x1=420, x2=480, y1=200, y2=230),
        make_item(6, "Terms", y1=300, y2=330),
    ]
    assert row_mates(items) == {2: ["Bruno Mars", "Sep 25"], 5: ["Coldplay", "Oct 2"]}
    wide = [make_item(i, f"Col {i}", x1=100 + 60 * i, x2=150 + 60 * i) for i in range(5)] + [
        make_item(5, "Buy", x1=420, x2=480),
        make_item(6, "Buy", x1=420, x2=480, y1=200, y2=230),
    ]
    assert row_mates(wide)[5] == ["Col 0", "Col 1", "Col 2"]  # a criterion stays short
    assert row_mates(wide, limit=None)[5] == [f"Col {i}" for i in range(5)]  # a history line takes the whole row
    crit = item_criteria(screen, items)
    assert crit["5"].endswith("; in the row of 'Coldplay', 'Oct 2')")
    assert "row" not in crit["3"] and "row" not in crit["6"]
    state = base_state("buy a ticket to Coldplay", screen, items, [])
    rows = state["screen_items_in_reading_order"]
    assert rows[5]["beside"] == ["Coldplay", "Oct 2"] and "beside" not in rows[3]


def test_a_control_parked_far_off_the_display_still_gets_a_region(screen, make_item):
    above = make_item(0, "note row", x1=100, y1=-98_000, x2=400, y2=-97_970)
    below = make_item(1, "scrolled link", x1=3_000, y1=5_000, x2=3_400, y2=5_030)

    assert screen.region(above) == "top-left"
    assert screen.region(below) == "bottom-right"


def test_guidance_reaches_the_state_only_when_there_is_some(screen, make_item):
    items = [make_item(0, "Buy")]
    guided = Guidance().heard("13 or 15 inch?", "15").focused("Click '15 inch'")

    assert not {"current_focus", "user_said"} & set(base_state("buy the thing", screen, items, [], None, Guidance()))
    state = base_state("buy the thing", screen, items, [], None, guided)
    assert state["current_focus"] == "Click '15 inch'"
    assert state["user_said"] == [{"asked": "13 or 15 inch?", "replied": "15"}]
    assert list(state)[:3] == ["goal", "current_focus", "user_said"]  # beside the goal they refine


def test_the_item_question_steers_around_what_was_tried_here_as_the_kind_question_does(screen, make_item):
    """bb5e4c0d clicked 'Microsoft Bing' three times running. The click selected Bing's radio and
    changed no text, so each one led back to the same screen and joined the tried list, but only the
    kind question was told to steer around that list, and the item question chose Bing every time."""
    asked = []

    def system_one(state, questions):
        asked.append(questions)
        return SimpleNamespace(answers={"kind": answer("click_item", 0.9), "item": answer("1", 0.9), "site": answer("none", 1.0)})

    items = [make_item(0, "Microsoft Bing"), make_item(1, "Set as default", y1=200, y2=230)]
    tried = ["clicked 'Microsoft Bing'"]
    decide(SimpleNamespace(system_one=system_one), "make Bing the default", screen, items, [], "Google Chrome", None, tried)

    (questions,) = asked
    for key in ("kind", "item"):
        assert "already tried on this screen" in questions[key].instructions
        assert "led straight back here" in questions[key].instructions


def asked_questions(screen, browsers):
    """The questions decide sends for one screen, with the installed browsers given."""
    asked = []

    def system_one(state, questions):
        asked.append(questions)
        return SimpleNamespace(answers={"kind": answer("use_browser", 0.9), "site": answer("none", 1.0)})

    decide(
        SimpleNamespace(system_one=system_one),
        "open openrouter in Brave",
        screen,
        [],
        [],
        "Google Chrome",
        None,
        browsers=browsers,
    )
    (questions,) = asked
    return questions


def test_one_browser_asks_no_browser_question(screen):
    questions = asked_questions(screen, ())
    assert "browser" not in questions
    assert questions["kind"].criteria["use_browser"].startswith("Work in Google Chrome:")
    assert "browser" not in asked_questions(screen, ("Google Chrome",))


def test_more_browsers_ask_which_one_and_the_answer_reaches_the_decision(screen):
    """'in Brave open openrouter' opened Chrome, the one browser the run knew."""
    questions = asked_questions(replace(screen, app="Brave Browser"), ("Brave Browser", "Google Chrome", "Arc"))
    assert list(questions["browser"].criteria) == ["Google Chrome", "Brave Browser", "Arc"]
    assert questions["kind"].criteria["use_browser"].startswith("Work in a web browser (the browser question says which)")

    def system_one(state, questions):
        return SimpleNamespace(
            answers={"kind": answer("use_browser", 0.9), "site": answer("none", 1.0), "browser": answer("Brave Browser", 0.8)}
        )

    d = decide(SimpleNamespace(system_one=system_one), "g", screen, [], [], "Google Chrome", None, browsers=("Brave Browser",))
    assert d.browser.choice == "Brave Browser" and d.confidence == 0.9  # a split on the browser never stops the run


def test_open_app_is_offered_only_when_there_are_apps_to_open():
    assert "open_app" not in kind_criteria("Google Chrome", None)
    assert "open_app" in kind_criteria("Google Chrome", None, apps=("Photos",))


def test_app_criteria_mark_the_app_in_front_and_offer_none():
    assert app_criteria(("Notes", "Photos"), "Notes") == {
        "Notes": "Open Notes (the app in front now).",
        "Photos": "Open Photos.",
        "none": "None of these apps is the one the goal needs.",
    }


def test_the_app_is_asked_in_a_second_request_only_once_open_app_is_chosen(screen):
    """The app list is long and most steps open no app, so the step's request leaves it out."""
    requests = []

    def system_one(state, questions):
        requests.append((state, questions))
        if "app" in questions:
            return SimpleNamespace(answers={"app": answer("Photos", 0.7)})
        return SimpleNamespace(answers={"kind": answer(kind, 0.95), "site": answer("none", 1.0)})

    client = SimpleNamespace(system_one=system_one)
    goal = "Open Photos and tell me roughly how many screenshots I took this month"
    kind = "click_item"
    assert decide(client, goal, screen, [], [], "Google Chrome", None, apps=("Photos", "Notes")).app is None
    assert len(requests) == 1 and "app" not in requests[0][1]

    requests.clear()
    kind = "open_app"
    d = decide(
        client, goal, screen, [], [], "Google Chrome", None, guidance=Guidance(focus="open Photos"), apps=("Photos", "Notes")
    )
    assert d.chosen == "open_app" and d.app.choice == "Photos" and d.confidence == 0.95  # a split on the app never stops the run
    state, questions = requests[1]
    assert state == {"goal": goal, "current_focus": "open Photos", "frontmost_app": "Google Chrome"}
    assert list(questions["app"].criteria) == ["Photos", "Notes", "none"]


def test_browser_criteria_say_which_is_in_front_and_which_is_the_default():
    crit = browser_criteria("Google Chrome", ("Brave Browser", "Google Chrome"), "Brave Browser")
    assert crit == {
        "Google Chrome": "Work in Google Chrome (the default).",
        "Brave Browser": "Work in Brave Browser (the app in front now).",
    }
    assert browser_criteria("Google Chrome", (), "Google Chrome") == {
        "Google Chrome": "Work in Google Chrome (the app in front now; the default)."
    }


def test_a_stand_in_field_is_checked_against_the_screen_text_across_its_row():
    """The browser hid the box, so there is no value to read back and no focus to compare: the
    check reads what the screen shows across the box's row, and says that is what it is."""
    states = []

    def system_one(state, questions):
        states.append(state)
        return SimpleNamespace(answers={"ok": SimpleNamespace(noul=0.9)})

    box = Field(role="", label="10", placeholder="", value="", x=500, y=300, w=20, h=16, clicked=True)
    after = replace(box, value="Amount | 0.29")
    assert verify_typed(SimpleNamespace(system_one=system_one), "top up to $10", box, "0.29", after) == 0.9
    (state,) = states
    assert state["screen_text_across_the_field_row_now"] == "Amount | 0.29"
    assert "field_value_now" not in state and "field_still_focused" not in state
    assert state["field"]["role"] == "unknown"

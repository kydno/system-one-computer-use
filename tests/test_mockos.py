"""The mock OS without a browser: the adapter against a canned page, the tasks, the caches, the rows.

The page itself runs only in Chromium (`clicker-mock check`); here every call into it is a fake that
records what was asked and answers with a fixed snapshot.
"""

from __future__ import annotations

import base64
import copy
import json
from io import BytesIO
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image, ImageDraw

from typesafe_computer_use import dates, decide, perception, runner
from typesafe_computer_use import writer as writer_module
from typesafe_computer_use.actions import Context
from typesafe_computer_use.decisions import Choice, Endpoint
from typesafe_computer_use.evals.budget import BudgetError, Ledger
from typesafe_computer_use.mockos import compare, passes, profile, replay
from typesafe_computer_use.mockos.desktop import FieldRef, MockDesktop, Node, lines_in
from typesafe_computer_use.mockos.page import MockPage
from typesafe_computer_use.mockos.tasks import OracleError, build, find_item, oracle_policy, says, select
from typesafe_computer_use.mockos.tasks import settings as settings_tasks
from typesafe_computer_use.platform_adapter import current, using
from typesafe_computer_use.runner import RunConfig
from typesafe_computer_use.stand_ins import FakeTypeSafe, FakeWriter, scripted

WINDOW = [180, 60, 1080, 768]


def png(size=(1440, 900), color=(240, 240, 240)) -> str:
    """A capture with the switch drawn where the tree says it is: a control with no ink reads as hidden."""
    buffer = BytesIO()
    image = Image.new("RGB", size, color)
    ImageDraw.Draw(image).rounded_rectangle((1150, 140, 1188, 162), radius=10, outline=(60, 60, 60), fill=(52, 168, 83))
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def snapshot(n: int = 1, focus: dict | None = None) -> dict:
    """A Settings window with a switch on screen, one scrolled out of its pane, and two lines of text."""
    switch = {"id": 11, "role": "AXCheckBox", "label": "Wireless", "frame": [1150, 140, 38, 22], "press": True, "children": []}
    parked = {
        "id": 12,
        "role": "AXCheckBox",
        "label": "Voice control",
        "frame": [1150, -4200, 38, 22],
        "press": True,
        "children": [],
    }
    text = {"id": 0, "role": "AXStaticText", "label": "Wireless", "frame": [500, 142, 70, 18], "press": False, "children": []}
    window = {
        "id": 5,
        "role": "AXWindow",
        "label": "Network",
        "frame": WINDOW,
        "press": False,
        "children": [text, switch, parked],
    }
    return {
        "id": n,
        "app": "Settings",
        "pid": 4101,
        "window": WINDOW,
        "url": None,
        "tabs": [],
        "focus": focus,
        "tree": {"id": 0, "role": "AXApplication", "label": "Settings", "frame": None, "press": False, "children": [window]},
        "lines": [
            ["Settings", 1.0, [40, 11, 100, 29]],
            ["Wireless", 1.0, [500, 142, 570, 160]],
            ["Dock", 1.0, [700, 860, 740, 880]],
        ],
    }


class FakePage:
    """`MockPage.call` and `session.call`, recorded, answering from a canned snapshot."""

    def __init__(self, focus: dict | None = None) -> None:
        self.calls: list[tuple] = []
        self.cdp_calls: list[tuple[str, dict]] = []
        self.n = 0
        self.focus = focus

    def call(self, name: str, *args):
        self.calls.append((name, *args))
        if name in ("hold", "snapshot"):
            self.n += 1
            return snapshot(self.n, self.focus)
        if name == "apps":
            return ["Settings", "Chromium"]
        if name.startswith("ax.") or name in ("release", "launch", "clearField"):
            return "" if name == "ax.value" else True
        raise AssertionError(f"unexpected call {name}")

    def cdp(self, method: str, params: dict) -> dict:
        self.cdp_calls.append((method, params))
        return {"data": png()} if method == "Page.captureScreenshot" else {}


@pytest.fixture
def page() -> FakePage:
    return FakePage()


@pytest.fixture
def adapter(page) -> MockDesktop:
    return MockDesktop(page.call, page.cdp)


# ----- the adapter ---------------------------------------------------------------------------------


def test_a_screenshot_holds_the_page_around_the_capture_and_queries_answer_from_its_snapshot(adapter, page):
    image = adapter.screenshot()
    assert [c[0] for c in page.calls] == ["hold", "release"]
    assert image.size == (1440, 900) and image.info["snapshot"] == 1
    assert adapter.frontmost_app_and_pid() == ("Settings", 4101)
    assert adapter.frontmost_window_bounds() == tuple(float(v) for v in WINDOW)
    assert adapter.keyboard_focus().app == "Settings"
    assert [c[0] for c in page.calls] == ["hold", "release"], "no round trip after the snapshot"


def test_input_makes_the_snapshot_stale(adapter, page):
    adapter.screenshot()
    adapter.click_at((10.0, 20.0))
    adapter.frontmost_app_and_pid()
    assert page.calls[-1] == ("snapshot",)
    moves = [p for m, p in page.cdp_calls if m == "Input.dispatchMouseEvent"]
    assert [p["type"] for p in moves] == ["mouseMoved", "mousePressed", "mouseReleased"]
    assert moves[1]["button"] == "left" and moves[1]["clickCount"] == 1


def test_a_double_right_click_counts_its_clicks(adapter, page):
    adapter.click_at((5.0, 5.0), button="right", count=2)
    pressed = [p for m, p in page.cdp_calls if m == "Input.dispatchMouseEvent" and p["type"] == "mousePressed"]
    assert [(p["button"], p["clickCount"]) for p in pressed] == [("right", 1), ("right", 2)]


def test_text_in_a_crop_is_the_snapshots_lines_inside_it_in_the_crops_own_pixels(adapter):
    image = adapter.screenshot()
    with using(adapter):
        lines = perception.ocr_crop(image, (400.0, 100.0, 900.0, 300.0))
    assert lines == [("Wireless", 1.0, (500, 142, 570, 160))], "ocr_crop adds the origin back"
    crop = image.crop((400, 100, 900, 300))
    assert crop.info["origin"] == (400, 100) and crop.info["snapshot"] == 1
    assert adapter.recognize_text(crop) == [("Wireless", 1.0, (100, 42, 170, 60))]
    assert len(adapter.recognize_text(image)) == 3


def test_a_crop_of_a_crop_adds_both_origins():
    lines = [["x", 1.0, [110, 220, 130, 240]]]
    assert lines_in(lines, (100, 200), (50, 50)) == [("x", 1.0, (10, 20, 30, 40))]
    assert lines_in(lines, (0, 0), (100, 100)) == []


def test_controls_come_from_the_tree_and_a_parked_one_is_offered_off_screen(adapter):
    adapter.screenshot()
    found, offscreen, capped = adapter.actionable_elements(4101, 1440, 900)
    assert [(n.role, n.label) for n in found] == [("AXCheckBox", "Wireless")]
    assert [(n.role, n.label) for n in offscreen] == [("AXCheckBox", "Voice control")]
    assert not capped
    assert isinstance(found[0].ref, Node) and found[0].ref.id == 11


def test_a_press_goes_to_the_element_by_its_id_and_a_stray_ref_is_refused(adapter, page):
    adapter.screenshot()
    found, _, _ = adapter.actionable_elements(4101, 1440, 900)
    assert adapter.ax_press(found[0].ref)
    assert page.calls[-1] == ("ax.press", 11)
    assert not adapter.ax_press(object())


def test_the_focused_field_and_its_value(page):
    page.focus = {
        "id": 21,
        "role": "AXSearchField",
        "label": "Search",
        "placeholder": "Search",
        "value": "wire",
        "frame": [190, 112, 230, 28],
        "caret": 4,
        "selected": "",
    }
    adapter = MockDesktop(page.call, page.cdp)
    field = adapter.focused_field()
    assert (field.role, field.label, field.value, field.caret, field.is_text) == ("AXSearchField", "Search", "wire", 4, True)
    assert field.ref == FieldRef(21)
    assert adapter.ax_set_value(field.ref, "wireless")
    assert page.calls[-1] == ("ax.setValue", 21, "wireless")


def test_keys_go_in_as_cdp_key_events(adapter, page):
    adapter.press("return")
    adapter.press("[", command=True)
    adapter.press("f", control=True)
    downs = [p for m, p in page.cdp_calls if m == "Input.dispatchKeyEvent" and p["type"] != "keyUp"]
    assert (downs[0]["key"], downs[0]["type"], downs[0]["text"]) == ("Enter", "keyDown", "\r")
    assert (downs[1]["key"], downs[1]["modifiers"], downs[1]["type"]) == ("[", 4, "rawKeyDown")
    assert (downs[2]["key"], downs[2]["modifiers"]) == ("f", 2)
    with pytest.raises(ValueError):
        adapter.press("hyper")


def test_a_scroll_with_no_point_goes_over_the_windows_center(adapter, page):
    adapter.screenshot()
    adapter.scroll(-10)
    wheel = next(p for m, p in page.cdp_calls if p.get("type") == "mouseWheel")
    assert (wheel["x"], wheel["y"], wheel["deltaY"]) == (180 + 540, 60 + 384, 400)


def test_typing_inserts_text_and_the_browser_is_left_out_of_the_apps(adapter, page):
    adapter.type_text("hello")
    assert ("Input.insertText", {"text": "hello"}) in page.cdp_calls
    assert adapter.installed_apps() == ["Settings"]
    assert adapter.open_url("Chromium", "https://shop.mockos.example/") is False


def test_the_page_reaches_chromium_only_through_cdp_which_tests_refuse():
    with pytest.raises(RuntimeError, match="real machine"):
        MockPage().start()


# ----- the loop drives the adapter ----------------------------------------------------------------


def test_the_real_loop_runs_on_the_adapter_with_a_scripted_decision_client(tmp_path, page, monkeypatch):
    """One step of `runner.run` against the canned page: capture, perception, a press, the settle."""
    monkeypatch.setattr(runner, "settle", lambda *a, **k: None)
    fake = FakeTypeSafe(oracle_policy((("click_item", ("Wireless", "checkbox")),)))
    adapter = MockDesktop(page.call, page.cdp)
    cfg = RunConfig(goal="turn on wireless", out=tmp_path / "run", act=True, steps=3, delay=0)

    def ctx(typesafe, history):
        return Context(goal=cfg.goal, browser="Chromium", email=None, typesafe=typesafe, writer=FakeWriter(), history=history)

    with using(adapter):
        state = runner.run(cfg, ctx, decisions=lambda: fake)
    assert current() is not adapter
    assert state.history[0].startswith("pressed 'Wireless'")
    assert ("ax.press", 11) in page.calls
    assert state.outcome == "done"


def test_run_still_builds_its_own_client_when_none_is_given(tmp_path, monkeypatch):
    built = []

    class Client(FakeTypeSafe):
        def __init__(self):
            super().__init__(scripted())
            built.append(self)

    monkeypatch.setattr(runner, "DecisionClient", Client)
    monkeypatch.setattr(runner, "capture", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no screen here")))
    with pytest.raises(RuntimeError, match="no screen here"):
        runner.run(RunConfig(goal="g", out=tmp_path, act=True, steps=1), lambda t, h: Context("g", "Chromium", None, t, None, h))
    assert len(built) == 1


def test_the_held_clock_is_what_both_models_read():
    with passes.held_clock("2026-03-14T09:41"):
        assert decide.now_context() == {"local_time": "2026-03-14 09:41 Saturday", "timezone": "UTC", "today": "2026-03-14"}
        assert writer_module.now_context()["today"] == "2026-03-14"
    assert decide.now_context is dates.now_context and writer_module.now_context is dates.now_context, "restored after"


# ----- tasks ------------------------------------------------------------------------------------------


def test_every_task_has_a_unique_id_a_goal_a_check_and_a_starting_state():
    tasks = select()
    assert len(tasks) >= 6
    assert len({t.id for t in tasks}) == len(tasks)
    for task in tasks:
        assert task.goal and callable(task.check) and 1 <= task.tier <= 4
        assert task.seed["front"] in task.seed["running"] and task.seed["clock"].startswith("2026-")
        assert {"settings", "files"} <= set(task.seed), "every app's content, for a task that opens another app"
        json.dumps(task.seed)  # what MockOS.load takes is plain JSON


def test_the_same_seed_builds_the_same_task_and_another_seed_another():
    assert build("settings/toggle@1").seed == build("settings/toggle@1").seed
    assert build("settings/toggle@1").seed != build("settings/toggle@2").seed


def test_a_template_alone_takes_the_default_seeds_and_a_bad_id_says_why():
    assert [t.id for t in select(["settings/popup"])] == ["settings/popup@1", "settings/popup@2"]
    with pytest.raises(KeyError, match="no template"):
        select(["files/nope@1"])
    with pytest.raises(KeyError, match="names no seed"):
        build("settings/popup@x")


def _row(state: dict, label: str) -> dict:
    return next(r for r in settings_tasks.rows_of(state["settings"]).values() if r["label"] == label)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_a_toggle_task_passes_only_once_its_switch_is_on_and_nothing_else_moved(seed):
    task = build(f"settings/toggle@{seed}")
    label = task.goal.removeprefix("Turn on ").removesuffix(" in Settings.")
    start = copy.deepcopy(task.seed)
    assert not task.check(start, None)
    done = copy.deepcopy(start)
    _row(done, label)["on"] = True
    assert task.check(done, None)
    other = next(r for r in settings_tasks.rows_of(done["settings"]).values() if r["kind"] == "switch" and r["label"] != label)
    other["on"] = not other["on"]
    assert not task.check(done, None), "a wrong click elsewhere fails the task"


def test_a_popup_and_a_radio_task_check_the_value_asked_for():
    for name in ("settings/popup@1", "settings/radio@1"):
        task = build(name)
        target = next(step for step in task.oracle if step[1][1] in ("menu item", "radio"))[1][0]
        state = copy.deepcopy(task.seed)
        row = next(
            r
            for r in settings_tasks.rows_of(state["settings"]).values()
            if target in r.get("options", ()) and r["value"] != target
        )
        assert not task.check(state, None)
        row["value"] = target
        assert task.check(state, None)


def test_a_question_is_checked_on_the_answer():
    task = build("settings/read-value@1")
    pane = next(p for p in task.seed["settings"]["panes"] if p["id"] == task.seed["settings"]["pane"])
    label = task.goal.removeprefix("What is ").removesuffix(" set to in Settings?")
    value = next(r["value"] for g in pane["groups"] for r in g["rows"] if r["label"] == label)
    assert task.check(task.seed, f"It is set to {value}.")
    assert not task.check(task.seed, "I could not find it.")
    assert task.read_only and task.oracle == ()


def test_the_target_of_a_visible_task_is_in_the_first_rows_of_the_open_pane():
    for task in select(["settings/toggle", "settings/popup", "settings/radio"]):
        s = task.seed["settings"]
        pane = next(p for p in s["panes"] if p["id"] == s["pane"])
        labels = [r["label"] for r in settings_tasks.in_view(pane)]
        assert any(label in task.goal for label in labels)


def test_says_ignores_case_and_spacing():
    assert says("It is  set to   Dark mode", "dark mode")
    assert not says(None, "x") and not says("light", "dark")


# ----- the oracle --------------------------------------------------------------------------------------

STATE = {
    "screen_items_in_reading_order": [
        {"i": 0, "text": "Wireless", "where": "top-left"},
        {"i": 1, "text": "Wireless", "where": "top-right", "role": "checkbox"},
        {"i": 2, "text": "Dark", "role": "radio", "beside": ["Theme", "Light"]},
        {"i": 3, "text": "Dark", "role": "radio", "beside": ["Sidebar", "Light"]},
    ]
}


def test_an_oracle_target_finds_its_item_by_text_role_and_row():
    assert find_item(STATE, "Wireless") == 1, "the control rather than the label beside it"
    assert find_item(STATE, ("Wireless", None)) == 1
    assert find_item(STATE, ("Wireless", "checkbox")) == 1
    assert find_item(STATE, ("Dark", "radio", "Sidebar")) == 3
    assert find_item(STATE, 0) == 0
    joined = {"screen_items_in_reading_order": [{"i": 0, "text": "Store files in the cloud Storage", "role": "cell"}]}
    assert find_item(joined, ("Store files in the cloud", "cell")) == 0, "a block perception joined with the line under it"
    with pytest.raises(OracleError, match="no item reads"):
        find_item(STATE, ("Dark", "button"))


def test_the_oracle_policy_takes_its_steps_in_order_then_says_done():
    policy = oracle_policy(
        (("click_item", ("Dark", "radio", "Theme")), ("press_offscreen", "Voice control"), ("type_text", None))
    )
    assert policy(STATE, {}) == ("click_item", 2)
    assert policy(STATE, {}) == ("press_offscreen", "Voice control")
    assert policy(STATE, {}) == ("type_text", None)
    assert policy(STATE, {}) == ("done", None)


def test_the_stand_in_writer_types_its_texts_in_order():
    writer = FakeWriter(texts=["first", "second"], text="after")
    schema = {"properties": {"fill": {}, "text": {}, "submit": {}, "reason": {}}}

    def fill():
        reply = writer.messages.create(
            output_config={"format": {"schema": schema}}, messages=[{"content": [{"type": "text", "text": "{}"}]}]
        )
        return json.loads(reply.content[0].text)["text"]

    assert [fill(), fill(), fill()] == ["first", "second", "after"]


# ----- caches and the budget ------------------------------------------------------------------------


class Inner:
    def __init__(self) -> None:
        self.asked = 0
        self.messages = SimpleNamespace(create=self.create)

    def create(self, **request):
        self.asked += 1
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text='{"ok": true}')],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=120, output_tokens=8, cost=0.0031),
        )


def test_the_writer_cache_pays_once_and_serves_the_same_reply_with_its_recorded_usage(tmp_path):
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.open(1.0, 1)
    inner = Inner()
    first = passes.CachedWriter(inner, tmp_path, 0, ledger)
    request = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}
    a = first.messages.create(**request)
    second = passes.CachedWriter(inner, tmp_path, 0, ledger)
    b = second.messages.create(**request)
    assert inner.asked == 1
    assert (first.sent, first.cached, second.sent, second.cached) == (1, 0, 0, 1)
    assert a.content[0].text == b.content[0].text == '{"ok": true}'
    assert (b.usage.input_tokens, b.usage.output_tokens, b.usage.cost) == (120, 8, 0.0031)
    assert ledger.current().spent_usd == pytest.approx(0.0031)
    assert second.recorded == pytest.approx(first.recorded, abs=1e-3)


def first_option(request: httpx.Request) -> httpx.Response:
    asked = json.loads(request.content)["questions"]
    answers = {
        n: {"type": "choice", "choice": next(iter(q["criteria"])), "confidence": 0.9, "probabilities": {}}
        for n, q in asked.items()
    }
    usage = {"input_tokens": 9, "output_tokens": 1, "cost": 0.001}
    return httpx.Response(200, json={"model": "vendor/model-1", "usage": usage, "answers": answers})


def test_the_decision_cache_pays_once_and_keeps_the_seconds_the_reply_took(tmp_path):
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.open(1.0, 1)
    where = Endpoint("openrouter", "https://decisions.example.com/v1", "key", "vendor/model-1")
    question = {"kind": Choice({"a": "the first", "b": "the second"})}
    clients = [passes.CachedDecisions(where, tmp_path, 0, ledger, transport=httpx.MockTransport(first_option)) for _ in range(2)]
    replies = [client.system_one(state={"goal": "g"}, questions=question) for client in clients]
    assert [(c.sent, c.cached) for c in clients] == [(1, 0), (0, 1)]
    assert replies[0] == replies[1] and replies[1].usage.cost == 0.001, "the cached reply keeps its recorded usage"
    assert clients[1].recorded == pytest.approx(clients[0].recorded, abs=1e-3)
    assert ledger.current().spent_usd == pytest.approx(0.001)


def test_another_repeat_is_another_sample(tmp_path):
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.open(1.0, 1)
    inner = Inner()
    for repeat in (0, 1):
        passes.CachedWriter(inner, tmp_path, repeat, ledger).messages.create(model="m")
    assert inner.asked == 2


def test_no_batch_or_cached_only_refuses_a_request_the_cache_lacks(tmp_path):
    with pytest.raises(BudgetError, match="no batch is open"):
        passes.CachedWriter(Inner(), tmp_path, 0, Ledger(tmp_path / "ledger.jsonl")).messages.create(model="m")
    with pytest.raises(BudgetError, match="cached-only"):
        passes.CachedWriter(Inner(), tmp_path, 0, passes.CachedOnly()).messages.create(model="m")
    with pytest.raises(BudgetError, match="no writer is configured"):
        passes.CachedWriter(None, tmp_path, 0, passes.CachedOnly()).messages.create(model="m")


def test_a_cached_only_pass_needs_no_key_to_name_its_decision_model(monkeypatch):
    for name in ("OPENROUTER_API_KEY", "TYPESAFE_API_KEY", "CLICKER_DECISION_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    assert passes.decision_endpoint({"decisions": "some/model"}, cached_only=True).model == "some/model"
    with pytest.raises(ValueError):
        passes.decision_endpoint({}, cached_only=False)


# ----- rows, compare, replay, profile -------------------------------------------------------------


def row(task: str, score: int, steps: int, cost: float, repeat: int = 0, settle: float = 0.5) -> dict:
    return {
        "task": task,
        "repeat": repeat,
        "score": score,
        "steps": steps,
        "oracle_steps": 1,
        "outcome": "done",
        "seconds": 10.0,
        "loop_seconds": 8.0,
        "model_seconds": 2.0,
        "timing": {"settle": settle},
        "calls": {"decision": {"m": {"requests": steps + 2, "input_tokens": 1000}}},
        "cost": cost,
        "spent": 0.0,
        "sent": 0,
        "cached": steps,
        "models": ["m"],
        "chromium": "Chrome/1",
        "settings": {},
    }


def test_compare_counts_flips_and_compares_cost_over_the_tasks_solved_in_both():
    a = [row("t/a@1", 1, 4, 0.01), row("t/b@1", 1, 6, 0.02), row("t/c@1", 0, 9, 0.05)]
    b = [row("t/a@1", 1, 3, 0.008), row("t/b@1", 0, 9, 0.04), row("t/c@1", 1, 5, 0.01)]
    out = compare.compare(a, b)
    assert "solved: 2/3 in A, 2/3 in B, 1 in both" in out
    assert "flipped: t/b@1 solved -> failed" in out and "flipped: t/c@1 failed -> solved" in out
    assert "t/a@1: 4 -> 3" in out


def test_compare_calls_a_move_within_the_spread_between_repeats_noise():
    a = [row("t/a@1", 1, 4, 0.01, 0), row("t/a@1", 1, 8, 0.01, 1)]
    b = [row("t/a@1", 1, 5, 0.01, 0), row("t/a@1", 1, 7, 0.01, 1)]
    assert "within the spread between repeats" in compare.compare(a, b)


def test_compare_warns_when_the_passes_ran_different_models():
    a, b = [row("t/a@1", 1, 4, 0.01)], [{**row("t/a@1", 1, 4, 0.01), "models": ["n"]}]
    assert "differ in models" in compare.compare(a, b)


def test_show_lists_rows_and_the_share_that_passed():
    out = compare.show([row("t/a@1", 1, 4, 0.01), row("t/b@1", 0, 6, 0.02)])
    assert "1/2 passed the check" in out and "FAIL" in out


def test_rows_are_read_by_pass_name_or_path(tmp_path):
    (tmp_path / "p1.jsonl").write_text(json.dumps(row("t/a@1", 1, 4, 0.01)) + "\n")
    assert compare.rows_of("p1", tmp_path)[0]["task"] == "t/a@1"
    assert compare.rows_of(str(tmp_path / "p1.jsonl"), tmp_path)[0]["steps"] == 4
    with pytest.raises(FileNotFoundError):
        compare.rows_of("nope", tmp_path)


def run_folder(tmp_path):
    folder = tmp_path / "run"
    folder.mkdir()
    Image.new("RGB", (40, 30)).save(folder / "step-001.png")
    items = [
        {"text": "Wireless", "source": "ax+ocr", "role": "checkbox"},
        {"text": "Network", "source": "ocr", "role": ""},
        {"text": "Network", "source": "ocr", "role": ""},
    ]
    (folder / "step-001-answers.json").write_text(
        json.dumps(
            {
                "app": "Settings",
                "url": None,
                "chosen": "1",
                "kind": "click_item",
                "confidence": 0.9,
                "items": items,
                "timing": {"settle": 0.4},
            }
        )
    )
    (folder / "run.json").write_text(
        json.dumps({"goal": "Turn on </script> Wireless", "outcome": "done", "history": ["pressed 'Wireless'"]})
    )
    return folder


def test_replay_writes_a_page_that_steps_through_the_run(tmp_path):
    folder = run_folder(tmp_path)
    page = replay.write(folder).read_text()
    assert "step-001.png" in page and "pressed 'Wireless'" in page
    assert "</script> Wireless" not in page, "screen text cannot close the script it sits in"
    index = replay.index(tmp_path / "pass", [{**row("t/a@1", 1, 4, 0.01), "outcome": "done"}])
    assert "t-a@1-r0/replay.html" in index.read_text()


def test_profile_counts_items_sources_roles_and_settle_per_app_without_any_text(tmp_path):
    run_folder(tmp_path)
    numbers = profile.from_runs(tmp_path)
    settings = numbers["Settings"]
    assert settings["steps"] == 1 and settings["items"]["p50"] == 3
    assert settings["source_share"] == {"ax+ocr": 0.333, "ocr": 0.667}
    assert settings["roles_per_step"] == {"checkbox": 1.0}
    assert settings["repeated_texts_per_step"] == 2
    assert settings["settle_seconds"]["p50"] == 0.4
    assert "Wireless" not in json.dumps(numbers) and "Network" not in json.dumps(numbers)
    assert "Settings" in profile.table(numbers)

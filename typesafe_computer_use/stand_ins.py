"""Stand-ins for both models, driven by a script, so the real step loop runs with no model behind it.

`FakeTypeSafe` answers the decision model's questions from a policy over the state the real
`decide` builds; `scripted` is the simplest policy, a list of steps. `FakeWriter` answers the
writer's three kinds of request from their schemas. The offline tests drive the loop through them
(`tests/world.py`), and the mock OS runs each task's scripted solution through them
(`clicker-mock check`), which proves a task can be solved without asking a model.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from types import SimpleNamespace

from .decide import POINTING
from .decisions import Endpoint, Noul

Step = tuple  # (kind, target) or (kind, target, confidence)
Policy = Callable[[dict, dict], Step]


DEFAULT_CONFIDENCE = 0.9  # comfortably over the runner's 0.4 floor, so a scenario stops for a reason


class FakeTypeSafe:
    """The classifier, replaced by a policy over the state the real `decide` builds.

    A policy returns (kind, target) and this maps the target to whatever key the question wants:
    the item's index for click_item and for a scroll aimed at an item, the off-screen control's key
    for press_offscreen, the site key for use_browser, the catalog name for press_shortcut and the app
    for open_app (each answered in its own request, with the step's second confidence). So a scenario never writes an index, and renumbering the page cannot break it.

    Every decision state lands in `states`, so a test can assert what the model was shown. The
    `verify_typed` Noul that `actions._type_text` makes is a different question about a different
    state, so it is answered without being recorded and `states` stays one entry per step.
    """

    endpoint = Endpoint("fake", "https://decisions.example.com/v1/decisions", "", "fake/decisions")

    def __init__(
        self,
        policy: Policy,
        noul: float = 0.95,
        read_only: bool = False,
        moves: bool = False,
        shortcuts: Callable[[dict], str] | None = None,
        plan: bool = False,
        changes: Callable[[dict], float] | None = None,
    ):
        self.policy = policy
        self.changes = changes  # how the changes-something question is answered, from its state; nothing changes without one
        self.change_states: list[dict] = []  # the state each changes-something question was sent
        self.plan = plan  # how the goal-needs-a-plan question is answered: closed unless a scenario opens it
        self.shortcuts = shortcuts  # decides the shortcut from the follow-up's own state, when a scenario wants that
        self.noul = noul
        self.read_only = read_only  # how the goal question at the start of a run is answered
        self.moves = moves  # how the goal-needs-moves question is: closed unless a scenario opens it
        self.states: list[dict] = []
        self.asked: list[dict] = []  # the questions each decision was asked, so a test can read the criteria offered
        self.pending: tuple = (
            None,
            DEFAULT_CONFIDENCE,
            DEFAULT_CONFIDENCE,
        )  # the last step's target, and its item and drop-target confidences, for a follow-up question
        self.follow_ups: list[dict] = []  # the state each shortcut follow-up was sent, which is all that request sees

    def __enter__(self) -> FakeTypeSafe:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def system_one(self, state: dict, questions: dict) -> SimpleNamespace:
        if "read_only" in questions:
            return SimpleNamespace(answers={"read_only": SimpleNamespace(noul=1.0 if self.read_only else 0.0)})
        if "moves" in questions:
            return SimpleNamespace(answers={"moves": SimpleNamespace(noul=1.0 if self.moves else 0.0)})
        if "plan" in questions:
            return SimpleNamespace(answers={"plan": SimpleNamespace(noul=1.0 if self.plan else 0.0)})
        if "changes" in questions:
            self.change_states.append(state)
            return SimpleNamespace(answers={"changes": SimpleNamespace(noul=self.changes(state) if self.changes else 0.0)})
        if any(isinstance(q, Noul) for q in questions.values()):
            return SimpleNamespace(answers={name: SimpleNamespace(noul=self.noul) for name in questions})
        if set(questions) == {"target"}:  # the follow-up to a drag_item: where it is dropped, named by text
            self.asked.append(questions)
            target, confidence = self.pending[0][1], self.pending[2]
            return SimpleNamespace(answers={"target": _answer(self._item_key(state, target), confidence)})
        if set(questions) == {"app"}:  # the follow-up to an open_app: the app the step named
            self.asked.append(questions)
            return SimpleNamespace(answers={"app": _answer(self.pending[0], self.pending[1])})
        if set(questions) == {"shortcut"}:  # the follow-up to a press_shortcut: the step's own target, not a new decision
            self.asked.append(questions)
            self.follow_ups.append(state)
            target, confidence = self.pending[:2]
            if self.shortcuts is not None:
                target = self.shortcuts(state)
            return SimpleNamespace(answers={"shortcut": _answer(target, confidence)})
        self.states.append(state)
        self.asked.append(questions)
        step = self.policy(state, questions)
        kind, target = step[0], step[1]
        offered = questions["kind"].criteria if "kind" in questions else {}
        if kind not in offered and kind not in ("done", "none"):
            raise AssertionError(f"the scenario takes {kind!r}, which the kind question did not offer: {sorted(offered)}")
        confidence = step[2] if len(step) > 2 else DEFAULT_CONFIDENCE
        asked_again = confidence[1] if isinstance(confidence, tuple) else confidence
        dropped = confidence[2] if isinstance(confidence, tuple) and len(confidence) > 2 else asked_again
        self.pending = (target, asked_again, dropped)
        return SimpleNamespace(answers=self._answers(state, questions, kind, target, confidence))

    def _answers(self, state: dict, questions: dict, kind: str, target, confidence: float | tuple[float, float]) -> dict:
        """A step's confidence is one figure for every answer, or (kind, item) when the two differ."""
        confidence, item_confidence = confidence[:2] if isinstance(confidence, tuple) else (confidence, confidence)
        answers = {"kind": _answer(kind, confidence), "site": _answer(target if kind == "use_browser" else "none", confidence)}
        if "item" in questions:
            aimed = kind in ("click_item", *POINTING, "drag_item") or (
                kind in ("scroll_down", "scroll_up") and target is not None
            )
            what = target[0] if kind == "drag_item" else target
            answers["item"] = _answer(self._item_key(state, what) if aimed else "0", item_confidence)
        if "offscreen" in questions:
            key = self._offscreen_key(state, target) if kind == "press_offscreen" else "0"
            answers["offscreen"] = _answer(key, confidence)
        return answers

    @staticmethod
    def _item_key(state: dict, text: str | int) -> str:
        """The item's key: a policy names it by text, or by index when several items read the same."""
        if isinstance(text, int):
            return str(text)
        for it in state["screen_items_in_reading_order"]:
            if it["text"] == text:
                return str(it["i"])
        raise AssertionError(
            f"no item reads {text!r}: the screen shows {[it['text'] for it in state['screen_items_in_reading_order']]}"
        )

    @staticmethod
    def _offscreen_key(state: dict, label: str) -> str:
        for node in state.get("offscreen_controls", []):
            if node["label"] == label:
                return str(node["k"])
        raise AssertionError(f"no off-screen control is labelled {label!r}")


def _answer(choice: str, confidence: float) -> SimpleNamespace:
    """One ChoiceAnswer. The distribution names only real keys, since the runner logs them by key."""
    return SimpleNamespace(choice=choice, confidence=confidence, probabilities={choice: confidence})


def scripted(*steps: Step) -> Policy:
    """A policy that replays the steps in order, one per decision, and says `done` once spent."""
    taken = []

    def policy(state: dict, questions: dict) -> Step:
        taken.append(state)
        return steps[len(taken) - 1] if len(taken) <= len(steps) else ("done", None)

    return policy


class FakeWriter:
    """Stands in for the Anthropic client, answering by which properties the request asks for.

    The three writer calls are told apart by their schemas, exactly as `writer.py` builds them:
    a field fill, a proposed URL, and the answer. The answer is the text of the screen the
    run stopped on, plus the text of any earlier screens the packet carries, so a scenario can
    assert through the answer both where the run ended and what it read on the way.

    `submit` is whether the field fill asks for Return after the text. `texts` gives one fill per
    request, in order, for a run that types more than once; `text` answers every fill after them.

    `reviews` scripts what the writer makes of each stop, one entry per answer asked for: a dict
    of the reply's fields, or a callable(packet) returning one. {"focus": ...} sends the classifier
    back, {"question": ...} asks the user, {"wait": True} has the run wait for the screen, {"scroll": "top"} has it scroll, and each
    says the goal is not reached yet. Once the script is spent, every stop is the goal achieved, as
    it is with no script at all.
    """

    def __init__(
        self,
        text: str = "",
        url: str = "",
        reviews: list | None = None,
        submit: bool = False,
        texts: list[str] | None = None,
        plan: str = "",
    ):
        self.requests: list[dict] = []
        self.plan = plan  # the plan a run's start asks for; empty declines it
        self.text = text
        self.texts = list(texts or [])
        self.submit = submit
        self.url = url
        self.reviews = list(reviews or [])
        self.packets: list[dict] = []  # the packet of every answer asked for, in order
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **request):
        self.requests.append(request)
        asked = set(request["output_config"]["format"]["schema"]["properties"])
        packet = json.loads(request["messages"][0]["content"][-1]["text"])
        if asked == {"fill", "text", "submit", "reason"}:
            text = self.texts.pop(0) if self.texts else self.text
            reply = {"fill": bool(text), "text": text, "submit": self.submit, "reason": "the goal names what to type"}
        elif asked == {"ok", "plan"}:
            reply = {"ok": bool(self.plan), "plan": self.plan}
        elif asked == {"ok", "url", "reason"}:
            reply = {"ok": bool(self.url), "url": self.url, "reason": "the goal names the site"}
        elif asked == {"achieved", "answer", "focus", "question", "wait", "scroll", "scroll_over"}:
            self.packets.append(packet)
            earlier = [text for screen in packet.get("earlier_screens", []) for text in screen["text"]]
            scripted = self.reviews.pop(0) if self.reviews else {}
            scripted = scripted(packet) if callable(scripted) else scripted
            reply = {
                "achieved": not scripted,
                "answer": " ".join(packet["screen_text_in_reading_order"] + earlier),
                "focus": "",
                "question": "",
                "wait": False,
                "scroll": "",
                "scroll_over": "",
                **scripted,
            }
        else:
            raise AssertionError(f"the writer was asked for {sorted(asked)}")
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(reply))])

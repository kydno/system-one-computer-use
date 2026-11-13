"""The mock OS's tasks: a goal, a starting state, a check on the final state, and a scripted solution.

A template builds a task from a seed: the seed picks the names, values and positions, so one
template gives many tasks. Tasks are synthetic and can be committed and quoted; nothing in one is
copied from a real run (see docs/mock-os-plan.md).

The oracle is the list of steps that solves a task, as (kind, target) pairs like the policies of
`tests/world.py`. A target names an item by its text, by (text, role), or by (text, role, beside),
where `beside` is a text on the same row that tells apart several items of one text and role; `oracle_policy` turns it into the item's index on the
screen the step is decided on, so a task never writes an index.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from ...decide import POINTING
from ...stand_ins import Policy, Step

Check = Callable[[dict, str | None], bool]  # the final state and the run's answer
Template = Callable[[int], "Task"]

ITEM_KINDS = frozenset({"click_item", *POINTING, "scroll_down", "scroll_up"})
DEFAULT_SEEDS = (1, 2)  # the seeds `list`, `check` and `run` take a template at, unless a task id names one


@dataclass(frozen=True)
class Task:
    id: str  # "settings/toggle@2": the template and the seed
    tier: int  # 1 to 4
    goal: str  # what a user would type
    seed: dict  # the state MockOS.load takes, including the clock and the app in front
    check: Check
    oracle: tuple[Step, ...]  # the steps that solve it
    writes: tuple[str, ...] = ()  # what the scripted writer types, in order, for the oracle
    replies: tuple[str, ...] = ()  # what the scripted user answers when the writer asks a question
    steps: int = 30  # the step limit
    tags: tuple[str, ...] = ()  # the loop paths it exercises
    read_only: bool = False  # the goal only asks something: how the oracle's stand-in answers the gate
    reviews: tuple[dict, ...] = ()  # what the oracle's writer makes of each stop, as `FakeWriter` takes them
    url: str = ""  # the address the oracle's writer proposes when the run opens a site outside the catalog
    trap: bool = False  # nothing can be done: the run passes only when it changed nothing and did not claim success

    @property
    def template(self) -> str:
        return self.id.split("@", 1)[0]


TEMPLATES: dict[str, tuple[int, Template]] = {}  # id -> (tier, template)


def template(name: str, tier: int) -> Callable[[Template], Template]:
    def register(fn: Template) -> Template:
        if name in TEMPLATES:
            raise ValueError(f"two templates are named {name!r}")
        TEMPLATES[name] = (tier, fn)
        return fn

    return register


def rng(name: str, seed: int) -> random.Random:
    """The generator a template draws from: the same names and values for the same template and seed,
    on every machine and every Python."""
    return random.Random(f"{name}@{seed}")


def build(task_id: str) -> Task:
    """One task by its id, "<template>@<seed>"."""
    name, _, seed = task_id.partition("@")
    if name not in TEMPLATES:
        raise KeyError(f"no template named {name!r}; `clicker-mock list` lists them")
    if not seed.isdigit():
        raise KeyError(f"{task_id!r} names no seed: write it as {name}@<number>")
    task = TEMPLATES[name][1](int(seed))
    if task.id != task_id:
        raise AssertionError(f"template {name!r} built {task.id!r} for {task_id!r}")
    return task


def every(seeds: Iterable[int] = DEFAULT_SEEDS) -> list[Task]:
    _load()
    return [build(f"{name}@{seed}") for name in sorted(TEMPLATES) for seed in seeds]


def select(ids: Iterable[str] = (), tier: int | None = None, tag: str | None = None) -> list[Task]:
    """The tasks a command names: by id (a template alone takes the default seeds), else all of them;
    then those of `tier` and with `tag`."""
    _load()
    ids = list(ids)
    tasks = [t for i in ids for t in _named(i)] if ids else every()
    return [t for t in tasks if (tier is None or t.tier == tier) and (tag is None or tag in t.tags)]


def _named(name: str) -> list[Task]:
    """A task id, a template at its default seeds, or a family ("settings") at all of its templates."""
    if "@" in name:
        return [build(name)]
    if "/" not in name:
        family = sorted(t for t in TEMPLATES if t.startswith(f"{name}/"))
        if not family:
            raise KeyError(f"no template named {name!r}; `clicker-mock list` lists them")
        return [build(f"{t}@{s}") for t in family for s in DEFAULT_SEEDS]
    return [build(f"{name}@{s}") for s in DEFAULT_SEEDS]


def _load() -> None:
    """Register every template module's templates."""
    from . import files, settings  # noqa: F401


def desktop(r: random.Random, front: str, running: Iterable[str] = (), **given: dict) -> dict:
    """A starting state: every app's content drawn from `r`, `given` in place of an app's own (by its
    state key: settings, files, ...), the clock, the page's own seed, and the apps running."""
    from . import files, settings

    content = {"settings": settings.content, "files": files.content}
    state = {key: given[key] if key in given else build_content(r) for key, build_content in content.items()}
    return {
        "clock": given.get("clock") or clock(r),
        "rng": r.randint(1, 2**31 - 1),
        "front": front,
        "running": list(dict.fromkeys([*running, front])),
        **state,
    }


def clock(r: random.Random) -> str:
    """A moment in 2026, on a weekday morning or afternoon."""
    month, day = r.randint(1, 12), r.randint(1, 28)
    return f"2026-{month:02d}-{day:02d}T{r.randint(8, 18):02d}:{r.choice((0, 5, 12, 20, 34, 41, 47, 55)):02d}"


# ----- the oracle ------------------------------------------------------------------------------


class OracleError(AssertionError):
    """An oracle step names no item on the screen: the task, or the mock app, is wrong."""


def find_item(state: dict, target) -> int:
    """The index of the item a target names, on the screen `state` describes."""
    if isinstance(target, int):
        return target
    text, role, beside = (target, None, None) if isinstance(target, str) else (*target, None, None)[:3]
    items = state["screen_items_in_reading_order"]
    found = [it for it in items if it["text"] == text and (role is None or it.get("role") == role)]
    if not found:  # perception joined the text with the line under it into one block, as for a result and its pane
        found = [it for it in items if it["text"].startswith(f"{text} ") and (role is None or it.get("role") == role)]
    if beside is not None and len(found) > 1:
        found = [it for it in found if beside in it.get("beside", ())]  # the one on the row of that text
    if role is None and len(found) > 1:
        found = [it for it in found if it.get("role")] or found  # a control rather than the label beside it
    if not found:
        raise OracleError(f"no item reads {target!r}: the screen shows {[(it['text'], it.get('role', '')) for it in items]}")
    return int(found[0]["i"])


def oracle_policy(steps: tuple[Step, ...]) -> Policy:
    """A policy that takes the oracle's steps in order, one per decision, and says `done` once spent."""
    taken: list[dict] = []

    def policy(state: dict, questions: dict) -> Step:
        taken.append(state)
        n = len(taken) - 1
        if n >= len(steps):
            return ("done", None)
        kind, target, *rest = steps[n]
        if kind in ITEM_KINDS and target is not None:
            target = find_item(state, target)
        elif kind == "drag_item":
            target = (find_item(state, target[0]), find_item(state, target[1]))
        return (kind, target, *rest)

    return policy


# ----- checks --------------------------------------------------------------------------------


def says(answer: str | None, *values: str) -> bool:
    """Whether the answer holds every value, ignoring case and runs of spaces."""
    if not answer:
        return False
    flat = " ".join(answer.split()).casefold()
    return all(" ".join(v.split()).casefold() in flat for v in values)

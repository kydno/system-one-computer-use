# Mock OS

A fake desktop in a Chromium page that the real step loop drives, for evals that react and cost
cents. The design and its reasoning are in [mock-os-plan.md](mock-os-plan.md); this page is how to
use it.

The loop runs as it ships: `runner.run`, `decide`, `actions`, `perception` and the writer, inside
`platform_adapter.using(MockDesktop(...))`, as an OSWorld run drives a VM. Only the computer is
fake. A pass measures what a change does to steps, requests, tokens, dollars and seconds, and
whether the tasks still get done.

## Commands

```
clicker-mock list [--tier N] [--tag T]       the tasks; no browser
clicker-mock check [TASK ...]                each task's scripted solution through the real loop: no model, no batch
clicker-mock run [TASK ...] [--repeats N]    a pass with the real models, cached, inside an open batch
                 [--headed] [--ocr dom|rapidocr|vision] [--latency instant|typical|slow]
                 [--cached-only | --no-cache] [--name NAME]
clicker-mock compare PASS_A PASS_B           what changed between two passes; no browser
clicker-mock show PASS [TASK]                a pass's rows, or one run's; no browser
clicker-mock open TASK                       a task's starting state, headed, to try by hand
clicker-mock replay RUN_FOLDER               write replay.html for a run folder; no browser
clicker-mock profile runs [--from DIR]       what the loop saw of each app, in numbers; reads files only
```

A task is named `<template>@<seed>`, as in `settings/toggle@2`. A template alone (`settings/toggle`)
takes its default seeds, and an app alone (`settings`) takes all of its templates.

`check`, `run` and `open` start a Chromium on a throwaway profile. **On the maintainer's Mac that
needs their yes for each command**, headless or headed, as any browser does ([AGENTS.md](../AGENTS.md)).
In `scripts/sandbox`, in CI, or in a cloud session it does not.

## The desktop

A 1440 x 900 display at scale 1: a bar along the top with the app in front and the clock, the
windows below it, and a dock along the bottom. The apps and sites:

| App | What it has |
|---|---|
| Settings | Fifteen panes in a sidebar, switches, popup menus, radio groups, a search, a pane that scrolls, rows that share one Options… button, a reset behind a confirmation sheet |
| Files | Places, a sortable list, open, new folder, rename in place, Move to…, a Trash that asks first and puts back, a context menu, dragging a row onto a folder |
| Chromium | Tabs, Back, Reload, an address field; a progress bar and an empty page for a moment after each navigation |
| Mail | Mailboxes, a list with a Flag and an Archive button on every row, a reading pane, search, a sheet to write or reply in |
| Calendar | A month grid, the chosen day's events, a sheet with a date picker and a start time |
| Notes | A list and one text area; a new note takes the keyboard at once |

| Site | What it has |
|---|---|
| `https://shop.mockos.example/` | A catalogue, a search, a cart, a checkout button that answers only to pointer events, a checkout form, a newsletter, a cookie banner over the bottom rows |
| `https://tickets.mockos.example/` | Events A to Z with their dates and prices, ticket tiers, a checkout; a listing that can load slowly |
| `https://wiki.mockos.example/` | Long articles, a search, and links that may lead nowhere |

Any other address shows a page that says it is not part of the mock OS. Chromium starts with every
host name unresolved, so nothing outside the page can load.

The page lives in `typesafe_computer_use/mockos/web/`: plain HTML and classic scripts, loaded by
`file://`, with no build step and nothing fetched. `os.js` holds the one state object, the one way
to change it (`dispatch`, which logs every action), the seeded scheduler, and the snapshot the
adapter reads; `kit.js` is the controls every app is built from; `apps/` is one file per app.

## What the loop sees

`MockDesktop.screenshot()` holds the page's scheduler, takes one snapshot of the app in front, its
window, the focused field, the controls and every rendered line of text, captures the pixels, and
lets the scheduler go, so all of them describe the same instant. Every other read answers from that
snapshot until an input makes it stale.

- **Controls** come from the DOM's roles and labels, mapped to the Mac's names (`button` to
  `AXButton`, `switch` to `AXCheckBox`, `row` to `AXRow`, ...), and go through
  `ax_walk.walk_actionable` as the Mac's do. A control scrolled out of its pane is parked off the
  display, so the walk offers it as an off-screen control.
- **Text** is read from the page by default (`--ocr dom`): every rendered line with its box,
  deterministic and quick. Icons are not text. `rapidocr` and `vision` read the pixels instead, for
  measuring perception. A crop of a capture records where it came from, so `perception.py` needs no
  change.
- **Input** goes in as CDP input events: it never touches this machine's own pointer or keyboard. A
  press through accessibility is a DOM click, which a pointer-only control ignores, as on a Mac.

## Tasks

`typesafe_computer_use/mockos/tasks/`: one module per app family, 47 templates, each a goal, a
starting state, a check on the final state, and an oracle, the scripted steps that solve it.

```python
@template("settings/toggle", 1)
def toggle(seed: int) -> Task:
    r = rng("settings/toggle", seed)  # the same names and values for the same seed, anywhere
    settings = content(r)
    pane, row = pick(r, settings, SWITCH)
    row["on"] = False
    ...
    return Task(
        id=f"settings/toggle@{seed}",
        tier=1,
        goal=f"Turn on {row['label']} in Settings.",
        seed=desktop(r, "Settings", settings=settings),
        check=lambda final, answer: rows_of(final["settings"])[row["id"]]["on"] is True and ...,
        oracle=(("click_item", (row["label"], "checkbox")),),
    )
```

A check reads facts from the state the page dumps (where a file is, what a setting holds, what was
sent) and, for a question, whether the answer holds the value. No model judges anything. A trap task
(`trap=True`) passes only when nothing changed and the run did not claim success.

An oracle step names an item by its text, by (text, role), by (text, role, beside) for a text on the
same row, by (text, role, None, after) for the first match after an item, or by `MIDDLE` for whatever
sits in the middle of the screen. `reviews`, `writes`, `replies` and `url` script the writer and the
user. Everything in a task is made up; nothing is copied from a real run.

`clicker-mock check` runs every oracle through the real loop with the stand-ins for both models
(`stand_ins.py`), and fails a task whose check fails or whose run takes a different number of
actions than the oracle. It costs nothing and proves each task can be solved, so a failed pass is
the agent's failure and not the environment's.

## Passes

`clicker-mock run` asks the real models. Every reply is cached by its request in `.mockos/cache/`,
with the tokens, cost and seconds it was recorded with: a pass on unchanged code sends nothing, and
a change pays only for what it changed. Every real request is charged to the batch the user opened
with `clicker-eval batch open` (the same ledger), and the pass stops once the cap is spent, keeping
its rows. `--cached-only` sends nothing at all. `--repeats N` takes N samples of each task, kept
apart in the cache. The models are the environment's, unless `benchmarks/mockos/config.json` names
them (`decisions`, `writer`, `answer`).

Two passes on one commit build byte-identical requests: the page's clock is the seed's, the loop's
clock is held at it (`passes.held_clock`), randomness is seeded, and nothing animates.

Each run leaves its usual run folder in `.mockos/runs/<pass>/<task>-r<repeat>/`, with `mockos.json`
(the score and the final state) and `replay.html` (arrow keys to step through it); the pass gets an
`index.html`. Rows go to `benchmarks/mockos/<pass>.jsonl`: numbers and ids, never screen text.

| Field | What it holds |
|---|---|
| `task`, `tier`, `tags`, `repeat` | Which run of which task |
| `score`, `outcome`, `said_done` | The check, why the loop stopped, and the writer's own verdict |
| `steps`, `oracle_steps` | Actions taken, and the oracle's |
| `seconds`, `loop_seconds`, `model_seconds` | Wall time; time outside live model calls; recorded model time |
| `timing` | Mean seconds per step phase: capture, ocr, ax, decide, act, settle |
| `calls`, `cost`, `spent`, `sent`, `cached` | Per role and model; dollars as if live; dollars this pass paid; requests sent and served from the cache |
| `handoffs`, `questions`, `models`, `settings` | Trips to the writer, questions put, model ids, and the OCR mode and latency |
| `git_commit`, `git_dirty`, `chromium`, `machine` | What it ran on |

`clicker-mock compare A B` lists the tasks that flipped, then compares steps, requests per role,
tokens, cost, loop, settle and model seconds over the tasks solved in both, and calls a move within
the spread between repeats noise.

## What it cannot tell you

- A mock is cleaner than a real app: text is read perfectly in `dom` mode and a press always lands.
  A saving measured here is a claim to confirm on OSWorld or a supervised run.
- Seconds here are not seconds on a Mac: OCR costs nothing in `dom` mode. The mock measures what the
  loop decides to do with time, not what the machine takes to read a screen.
- The apps are built to a provisional density. The survey of the real apps
  ([plan](mock-os-plan.md#modeling-the-apps-on-real-ones)) needs the maintainer's Mac and has not been
  done; `clicker-mock profile runs` gives the first numbers from the run folders already there.
- Tuning `decide.py` until the mock's tasks pass makes the number meaningless. The suite guards
  speed and cost work; it is not a target for capability work.

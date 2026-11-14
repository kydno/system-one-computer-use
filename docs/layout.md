# Layout

```
typesafe_computer_use/
  platform_adapter.py
                  `desktop`, the one way to the platform: windows.py on Windows,
                  macos.py everywhere else; `Desktop` names what both provide
  macos.py        the macOS adapter: Quartz, AX, AppleScript, Vision OCR
  windows.py      the Windows adapter (experimental): UI Automation, SendInput,
                  Windows.Media.Ocr
  ax_walk.py      the bounded accessibility-tree walk, shared by both adapters
  perception.py   capture, OCR, the read region and the changed-tile cache,
                  block merging, goal-echo filter, the accessibility item
                  source, and the merge of the two
  dates.py        date parsing and "in N days" hints
  decide.py       state, criteria, the three-Choice request, the Noul check
  decisions.py    the decision client: OpenRouter's Decisions API or TypeSafe's, one request schema
  writer.py       the writer model, structured replies, URL validation, the answer
                  with its focus or question
  openai_writer.py the writer's requests on an OpenAI-compatible endpoint
  actions.py      one handler per action, each returning a history line
  runner.py       the step loop, run folder, stop rules, the hand-off to the writer
                  and back
  calls.py        requests counted per model, at the two clients
  report.py       logging, annotated screenshots, payload dump
  timing.py       phase stopwatches, the timing line, run summary
  takeover.py     `clicker-takeover`: an LLM on OpenRouter drives on from a run's `handoff.json`
  cli.py          `clicker`, `clicker-inspect`, and `clicker-takeover`
  events.py       `clicker --events`: the run as JSON lines, replies on stdin
  osworld/        the agent in OSWorld (see [OSWorld](osworld.md))
    agent.py      `JevAgent`: OSWorld's reset() and predict(), the step loop on a worker thread
    desktop.py    the adapter over OSWorld's observation: screenshots in, pyautogui code out
    a11y.py       the Ubuntu accessibility tree OSWorld returns, in AX terms
    ocr.py        the OCR backends a run names
    results.py    each task's score, steps, time, and tokens, for `scripts/osworld results`
  evals/          `clicker-eval`: the offline eval kit (see [improvement loop](improvement-loop.md))
    store.py      where the kit keeps things: `runs/`, `.private/evals/`, `benchmarks/replay/`
    cases.py      freeze each saved step into a case, rebuild its request with the current code, score it
    decisions.py  ask the decision model about the cases again, with a reply cache and the budget in front
    budget.py     the batch ledger: a dollar cap and an iteration count, checked before every request
    digest.py     where real runs failed, in a table small enough to read
    size.py       request bytes by part, against a baseline
    report.py     the aggregate rows a pass leaves in `benchmarks/replay/`
    cli.py        `clicker-eval`
  mockos/         `clicker-mock`: a fake desktop in Chromium for reactive evals (see [mock OS](mock-os.md))
    web/          the page: os.js (state, dispatch, scheduler, snapshot), kit.js (controls), apps/
    page.py       Chromium started, sized, and loaded with a task
    desktop.py    `MockDesktop`: the Desktop surface over the page, one snapshot per screenshot
    tasks/        templates: a goal, a starting state, a check, and the oracle that solves it
    passes.py     the oracle check, and passes with cached, budgeted replies, into rows
    compare.py    a pass's rows, and what changed between two
    replay.py     replay.html for a run folder, index.html for a pass
    profile.py    what the loop saw of each app, in numbers
    cli.py        `clicker-mock`
  stand_ins.py    stand-ins for both models, driven by a script: the tests' and the mock's oracles
  browser/        the browser backend (see [browser backend](browser-backend.md)), opt-in and independent of macos.py
    cdp.py        the only module that touches the browser        (platform adapter)
    perceive.py   DOM collection: ordered elements, click points, occlusion
    decide.py     browser action set, two-Choice request, answer serialization
    act.py        real Input events, observe-until-changed
    runner.py     step loop, provenance, run folder
    report.py     run folder writing and offline replay
    bench.py      `clicker-bench`: DOM vs OCR, the step loop, replay
tests/            pure logic: dates, merging, reading order, echo filter, config,
                  decisions, the tree walk against a fake tree; for the browser
                  backend, parsing, action filtering, change detection, replay
  world.py        a simulated computer: pages, controls, fields, and what each action
                  does to them, driven by the real step loop with a policy as classifier
  test_scenarios.py
                  tasks of increasing difficulty on that computer, L1 upward; a failure
                  here says the architecture cannot do that task
osworld_overlay/  what `scripts/osworld setup` copies into OSWorld: the agent module and
                  the runner that builds it
scripts/          `sandbox` and `osworld`
menubar/          SystemOne.app, the menu bar front end, in Swift (see [menu bar app](menu-bar.md))
```

A Linux port adds a third adapter over xdotool, AT-SPI, and PaddleOCR or RapidOCR, and one line
in `platform_adapter.py`. The tree walk takes its children, attributes, and actions as callables,
so only those three bindings change per platform. Nothing else knows which OS it is running on.

The browser backend replaces `macos.py` with `browser/cdp.py` instead. Both are opt-in and
independent: a browser task never needs Screen Recording permission, and a canvas-only task
still wants the OCR path.

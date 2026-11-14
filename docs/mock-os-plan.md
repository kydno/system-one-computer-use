# Mock OS: a reactive eval tier that costs cents (plan)

**Status: built, except what needs the maintainer's Mac or a model key.** Phases 0 to 4 are in
the tree, with docs in [mock-os.md](mock-os.md): all six apps, the three sites, 47 templates, and
94 oracles that pass in headless Chromium. Not done: the survey of the real apps, so `profile
build` and `profile check`; tuning the suite to 70 to 85% solved and a first baseline pass, which
need the real models; a CI job, which is open question 3; and `scripts/sandbox run clicker-mock
check`, which was not run, for want of a Docker daemon where it was built. The open questions
below still stand. Where the build had to pick, it took the option that needs no answer: the
adapter-only crop (question 1), and hand-written DOM with the system's own font (question 2).

What follows is the plan as written on 2026-11-13 from a planning session with the maintainer,
kept as the design record. It gives the design, the reasoning behind each choice, the order to
build in, and what was open. Where it says "verify", the claim was a reasoned expectation that the
build had to confirm; everything else was read from the code at commit `038592c`.

Words used throughout:

- **task**: a goal in plain English, a starting state of the mock OS, and a check on the final state.
- **template** and **seed**: a template is a function that builds a task from a seeded random
  generator; the seed picks the names, prices, dates and positions, so one template gives many tasks.
- **oracle**: the scripted list of steps that solves a task, run with stand-ins for both models.
- **pass**: one run of a set of tasks, which leaves one row per task.
- **snapshot**: one consistent reading of the mock OS page: pixels, text, controls, focus.

## Why

`docs/improvement-loop.md` lists three tiers for judging a change and ends with the gap this fills:
"Offline cannot show that a new ability works, because the saved screens do not react. That needs
a tier that does." The two tiers that do react are expensive in different ways:

| Tier today | What a run costs |
|---|---|
| A supervised run on the maintainer's Mac | The maintainer's attention, and an approval for every command (`AGENTS.md`) |
| OSWorld | A Linux host with KVM in the cloud, a VM per task, and a fixed 2 s wait after every action. The agent's scored tasks recorded in `benchmarks/osworld/` took 37 to 134 s each for 3 to 11 steps |

A mock OS is a third reactive tier: a fake desktop with a few applications, small enough to start
in under a second and to run anywhere a Chromium runs. The real step loop drives it and the real
models answer, so a pass measures what a change does to steps, requests, tokens, dollars and
seconds, and whether the tasks still get done.

## What the maintainer decided

| Question | Decision |
|---|---|
| What it is built as | A web page in plain HTML and JS, run in Chromium. Not Electron, not Tauri, not a pure-Python simulation |
| What it is mainly for | Iterating on **speed and cost**. Capability still matters, but it is not what this environment is for |
| What a pass scores | Task success end to end, and the writer and hand-offs. A comparison against a frontier LLM agent is wanted later, not now |
| Applications in the first version | A browser with fake websites; Files and Settings; Mail, Calendar and Notes |
| Watching a run | Headless by default. A `--headed` flag to watch live at times, and a replay page for every run |
| `AGENTS.md` | Unchanged. An agent runs the mock OS without asking only in `scripts/sandbox`, in CI, or in a cloud session. On the Mac it proposes the command and waits, as for any browser |
| Realism | The apps should behave like the real ones as far as the loop can tell, modeled on a survey of the real apps on the maintainer's Mac. Raised after the first draft; see [Modeling the apps on real ones](#modeling-the-apps-on-real-ones) |
| This document | A draft pull request on the fork, for another agent to build from |

## Goals and non-goals

Goals, in order:

1. **Cheap.** A pass over the whole suite costs a few dollars at most with an empty cache and
   nothing when every request is cached (estimates, see [What a pass should cost](#what-a-pass-should-cost)).
2. **Fast.** Minutes for the whole suite, seconds for one task, no VM and no cloud machine.
3. **Comparable.** Two passes on the same commit give the same rows, so a difference between two
   commits is the change and not the weather.
4. **The real loop.** `runner.run`, `decide`, `actions`, `perception` and `writer` run as they ship.
5. **Realistic to the loop.** A mock screen gives the loop about as many items, of the same kinds,
   and changes about as fast, as the real app it stands for. Measured, not assumed.
6. **Little to build and little to add to.** A new task is a few lines; a new application is one file.

Non-goals:

- **A copy of macOS.** The mock matches the real apps in what the loop reads and in how long a
  screen takes to change. It does not copy how they look, and nothing is taken from inside an app.
  It borrows the Mac's layout (a bar along the top, windows, a dock) because the loop has rules
  about that layout.
- **Measuring perception.** The default reads text from the page, not from pixels. Real OCR is one
  flag away for the day that question comes up.
- **Replacing OSWorld or a supervised run.** A win on the mock is a claim to confirm on one of
  those, not proof (see [Risks](#risks-and-what-this-cannot-tell-you)).
- **Replacing `tests/world.py`.** That simulated computer runs the loop with a scripted policy, for
  free, in CI, and is where stop rules are tested. The mock OS answers a different question: what
  the real models do on whole tasks, and what that costs.

## What exists to build on

Most of the machinery is already in the repository. The build is mostly an adapter, a page, and a
task list.

| Path | What it gives the mock OS |
|---|---|
| `typesafe_computer_use/platform_adapter.py` | The `Desktop` protocol and `using(adapter)`, which swaps the computer the loop drives |
| `typesafe_computer_use/osworld/desktop.py`, `osworld/agent.py` | The pattern to copy: `OSWorldDesktop` implements `Desktop` over a remote computer, and `runner.run` runs unchanged inside `using(...)` |
| `typesafe_computer_use/browser/cdp.py` | `Chrome` and `Session`: a dedicated Chromium on a throwaway profile, headless or headed, with a loopback-only debugging socket |
| `typesafe_computer_use/ax_walk.py` | `walk_actionable`: the accessibility-tree walk with its pruning rules, written against callables so it can walk any tree |
| `typesafe_computer_use/osworld/a11y.py` | An example of feeding a foreign tree (AT-SPI XML) through that walk |
| `typesafe_computer_use/osworld/ocr.py` | `backend(name)`: RapidOCR or Vision by name, for runs that want real OCR |
| `typesafe_computer_use/evals/decisions.py` | `EvalClient`: the decision client with replies cached by request and every real request charged to the budget |
| `typesafe_computer_use/evals/budget.py` | `Ledger`: the dollar cap the maintainer approves, checked before each request |
| `typesafe_computer_use/evals/store.py` | `checkout_root`, `git_state`, `stamp`, `append_jsonl`: where files live and what commit a row was measured on |
| `typesafe_computer_use/evals/cases.py` | `frozen_clock`: holds the clock a request reads, so the same screen builds the same request tomorrow |
| `typesafe_computer_use/calls.py` | Requests, tokens and cost per model and per role, already written into every `run.json` |
| `tests/world.py` | `FakeTypeSafe`, `FakeWriter`, `scripted`: stand-ins for both models, driven by a policy |
| `scripts/sandbox`, `docs/sandbox.md` | A Linux container with Chromium and a noVNC tab, where an agent may run things without asking |
| `bench/fixture.html`, `browser/bench.py` | Precedent for loading a local page by `file://` |

## The shape

```
clicker-mock run                        new entry point: typesafe_computer_use/mockos/cli.py
  once per pass:
    Chromium, through browser/cdp.py    headless, or headed with --headed
  per task:
    load mockos/web/index.html          file://, nothing fetched
    MockOS.load(seed)                   the task's starting state
    with platform_adapter.using(MockDesktop(session)):
        runner.run(cfg, ctx_factory, decisions=...)     the real loop, unchanged
    final = MockOS.dump()
    score = task.check(final, the run's answer)         a check on state; no LLM judge
  out:
    benchmarks/mockos/<pass>.jsonl      one row per task: numbers and ids
    .mockos/runs/<pass>/<task>/         the usual run folder, plus replay.html
```

One step of a run, to show that nothing in the loop changes:

1. `perception.capture` calls `desktop.screenshot()`. `MockDesktop` takes a snapshot: it freezes
   the page's scheduler, reads the text lines, the control tree, the focus, the app and the URL in
   one call, captures the pixels, and releases the scheduler.
2. `capture` then asks for the app, the window, the focused field and the URL. Each is answered
   from that snapshot, with no further round trip.
3. `perception.perceive` asks for text (`recognize_text`) and controls (`actionable_elements`).
   Both are answered from the same snapshot, then merged by the loop's own code.
4. `decide` sends the request. The client is the production one with a cache under it and the
   budget in front of it.
5. `actions.perform` clicks, types or presses through the adapter, which sends real input events
   over CDP. `runner.settle` then watches the screen as it does on a Mac.

## The page

Lives in `typesafe_computer_use/mockos/web/`, inside the package so that an installed copy carries
it (verify that the wheel includes the non-Python files).

### Layout of the display

A fixed 1440 x 900 display at scale 1, set with CDP's `Emulation.setDeviceMetricsOverride` so
headless and headed runs render the same size.

- **A bar along the top, 40 px high.** `models.MENU_BAR_PT` is 40: the loop leaves that strip out
  of its change detection (`actions.moved`) and out of the screen's signature, because a real menu
  bar holds a clock. The mock puts its clock and the front app's name there and nothing a task
  depends on.
- **Windows below it.** One window per running app, the focused one on top, at a fixed frame. No
  moving or resizing in the first version: no task needs it, and `perception.ocr_region` reads the
  front window plus the strip above it, which a fixed frame keeps stable.
- **A dock along the bottom.** It is outside the front window, so the loop does not read it, as it
  does not read the real Dock. Apps are opened the way the loop opens them on a Mac: the
  `open_app` action, which calls the adapter's `activate`.

### State and the page's own API

One state object holds everything: the clock, the running apps and which is in front, and each
app's data (the file tree, the mailboxes, the calendar, the notes, the settings, the browser's tabs
and each site's data). Every change goes through one function, which appends to a log.

```js
MockOS.load(seed)          // replace the whole state; reset the clock, the RNG, the scheduler, the log
MockOS.dump()              // the state as JSON: what a task's check reads
MockOS.dispatch(action)    // the only way state changes; each action is appended to state.log
MockOS.after(ms, fn)       // the only timer an app may use; this is where seeded latency lives
MockOS.hold() / release()  // freeze and unfreeze the scheduler around a snapshot
MockOS.snapshot()          // {id, app, pid, window, url, tabs, focus, tree, lines}
MockOS.launch(app)         // bring an app to the front, starting it if needed
MockOS.browser.open(url)   // show a fake site in the mock browser
```

Why one state object with one way in: a task's check then reads facts ("the file is in that
folder", "one message was sent to that address") and never inspects the UI, a seed is plain JSON a
template can generate, and the log shows what a run did when a check fails.

### The kit, the apps, the sites

Applications are written against a small shared kit, so that each app is short and every control
reports itself the same way. The kit: window, toolbar, sidebar, list and table (selection, open,
context menu, drag onto a row), text field and text area, checkbox and switch, radio group, popup
menu, tabs, dialog and sheet, context menu, banner, spinner.

Every kit control carries its role and label in the DOM (`role`, `aria-label`, `aria-checked` and
so on). That is what the snapshot turns into the accessibility tree.

Recommended rendering: one small vendored library with no build step, for example Preact with htm
in its standalone single file, loaded as a classic script. Reason: with seven apps and three sites,
a declarative "state in, DOM out" renderer is the least code, and a text field keeps its focus and
caret across a re-render, which a hand-written re-render gets wrong first. The requirement is
only this: **no npm, no build step, nothing fetched at run time, classic scripts so `file://`
works.** Hand-written DOM code meets it too if the builder prefers.

| App | Modeled on | Must support in the first version |
|---|---|---|
| Files | Finder | Folders and files in a sidebar and a list; open, new folder, rename, move (drag onto a folder, and a "Move to" dialog), move to Trash with a confirmation, sort by a column, a context menu |
| Settings | System Settings | Panes in a sidebar; switches, radio groups, popup menus; a search field; one long pane that scrolls; one reset that asks for confirmation; nested rows with the same button on each |
| Chromium (the mock browser) | Google Chrome | An address field, tabs, back; renders the fake sites below |
| Mail | Mail | Mailboxes, a message list, a reading pane; compose, reply, send; flag and archive on each row; search |
| Calendar | Calendar | A month grid and a day list; create, edit and move an event; a date picker built from the kit |
| Notes | Notes | A list of notes and one text area; new note, edit, search |

The mock browser is named `Chromium`, a name in `config.BROWSER_APPS`, and is the run's configured
browser. Two of the loop's rules turn on a browser, and the mock should meet both as a Mac does:
a press has to show on screen whenever the capture reports a URL (`actions.press_showed`), and a
browser shortcut is refused when another app is in front (`actions._press_shortcut`).

Fake sites are rendered inside the mock browser's window by the same kit, picked by host name.
They live under a reserved top-level domain, which can never be a real site and which passes
`writer.valid_url` (https, a public-looking host name, not one of `PRIVATE_HOST_SUFFIXES`):

| Site | What it is for |
|---|---|
| `https://shop.mockos.example/` | A catalogue, a search box, a cart, a checkout form. Repeated "Add to cart" on every row, a cookie banner, one control that answers only to pointer events |
| `https://tickets.mockos.example/` | Events with dates and prices. Date arithmetic ("the next upcoming event"), the cheapest of several, a listing that loads slowly |
| `https://wiki.mockos.example/` | Articles with long pages, a search, and a dead link. Answers that sit below the fold or on an earlier page |

Any other address shows an in-page "this site is not part of the mock OS" page. Nothing is ever
fetched: Chromium is started with every host name unresolvable, so a stray real URL cannot load.

Things the page must not use, because they fall outside what the adapter can see or drive:

- Native `<select>`, `<input type="date">`, `alert()` and `confirm()`, and `title` tooltips. A
  native popup is drawn outside the page, and a native dialog blocks it. Build them from the kit.
- HTML5 drag and drop. Its events do not fire from the mouse events CDP sends (verify); the kit
  implements drag with pointer events.
- The system clipboard. Copy, cut and paste read and write `state.clipboard`. This also keeps a run
  on the Mac from touching the maintainer's clipboard.
- A control with no ink. `perception.drawn` treats a control whose box is one flat color with no
  border as hidden, so every control needs a label, an icon or a border.

### Determinism

Two passes on one commit must send byte-identical requests, or the cache misses and the rows
differ for no reason. So:

- **Clock.** The page shows the seed's time and never reads the real one. On the Python side the
  run is wrapped in `evals.cases.frozen_clock` with the same time, since `decide.base_state` puts
  the local time in every request.
- **Randomness.** A seeded generator in the page; `Math.random` and `Date.now` are not used.
- **Layout.** One bundled font, inlined in the stylesheet as a data URI so nothing is fetched.
  System fonts differ between a Mac and a Linux container, and a different line break reorders the
  items in a request.
- **Paint.** No animations, no transitions, no blinking caret, hidden scrollbars.
- **Time.** All latency goes through `MockOS.after`, so it is the same every run.

### Latency

Each action an app takes has a seeded delay from a profile the pass picks: `instant` (the same
frame), `typical` (about 100 to 600 ms, with a visible intermediate state where a real app has
one), or `slow` (a spinner for a few seconds on the pages a task marks). The default is `typical`.

Why not instant everywhere: over 604 saved steps settle was a third of all step time (the note in
`runner.settle_action`), and the loop's waits (`runner.settle`, `actions.press_showed`, the `wait`
action) only do anything when a screen takes time to change. With instant apps, a change to settle
logic would show no difference, and time is half of what this environment is for.

## Modeling the apps on real ones

The maintainer raised this after the first draft: the mock's apps may need to be realistic, and an
agent with computer use could study the real apps on the Mac to model them. This section says in
what sense realism matters here, and gives the procedure.

### What realistic has to mean

The loop never sees an app. It sees the items `perception.perceive` returns and how long the screen
takes to change. A mock app is realistic when those match the real app's:

| What to match | Why it matters for speed and cost |
|---|---|
| How many items a screen gives, and how many come from the tree, from text, or from both | The items are most of a request, and the classifier's input is most of the agent's cost (`OBSERVATIONS.md`). `docs/how-a-step-works.md` records 152 controls on a Finder screen and 172 in Chrome. A mock screen with thirty items would make every token count here several times too small |
| The mix of roles, the share of controls with no label, repeated labels, off-screen controls | They decide which path the loop takes: a press or a click, a row hint, `press_offscreen` |
| How long after an action the screen first changes, and how long until it holds still | That is what `runner.settle` waits on, and settle was a third of step time |
| The flows: which screens exist, and how many steps a job takes | Steps per task are the other half of the bill |

What does not need matching: colors, icons, fonts, exact positions. In the default mode pixels are
only compared with each other, to see whether the screen changed.

### What this is not

Nothing is taken from inside an application. No app bundle is opened, and no icon, string file,
interface file or binary is read or copied. The survey records only what a running app shows on
the screen and reports through the accessibility API, which is what the loop itself reads on every
step. The mock stays an original page with the same shape: a test double, not a copy.

### Two sources, cheapest first

1. **The run folders already on the Mac.** Every real run saved, for each step, the app in front,
   every item with its source and role, the off-screen controls, and the step's timing
   (`step-NNN-answers.json`; see `docs/run-folder.md`). `clicker-mock profile runs` reads them and
   writes numbers per app. It reads files and touches nothing, like `clicker-eval`, so it needs no
   approval. Its limit: it knows only the apps and screens that past runs happened to visit.
2. **A survey of each real app, state by state.** For the screens the run folders lack, and for
   the structure. It captures the maintainer's screen, so every command needs the maintainer's yes
   (`AGENTS.md`).

### The survey, step by step

Written for an agent with computer use on the Mac, working with the maintainer. Anything that can
see and drive the Mac may get an app into a state: an agent with computer use, or the maintainer's
own hands. The capture itself is always `clicker-inspect`, because the point is to record what
this loop reads, not what another tool sees.

Before starting:

1. **Use scratch data.** A separate macOS user account is best. Failing that: a scratch folder, a
   mailbox and a notes folder with made-up content, and a scratch calendar. A capture holds
   whatever is on the screen.
2. **Clear the screen.** Close other windows and turn on Do Not Disturb. Clear the terminal first,
   as the README says: it is on screen, so its text is OCR input.
3. **Agree the list.** For each app, write down the six to twelve states to capture, and get the
   maintainer's yes to the list, and then to each command as it comes.

| Mock app | Real app to survey | States worth capturing |
|---|---|---|
| Files | Finder | A folder of thirty or more files in list view; the sidebar; a context menu open on a file; a name being edited; the confirmation before the Trash; a search with results; an empty folder |
| Settings | System Settings | The first pane; a pane of switches; a pane long enough to scroll; a popup menu open; the search field with results; a confirmation sheet |
| Chromium and the sites | Google Chrome, on two or three public sites of the kinds the fake sites stand for: a shop, an event listing, a reference article | A listing; a product or event page; a form with a field focused; a cookie banner up; a page still loading; a long article scrolled half way |
| Mail | Mail | The message list; a message open; a new message with the body focused; a reply; search results |
| Calendar | Calendar | Month view; day view; a new event being edited; the date picker open |
| Notes | Notes | The list with a note open; a new empty note; a long note; search results |

For each state:

4. Get the app into the state. One approved action at a time when an agent drives.
5. Capture it:

   ```
   uv run clicker-inspect "<a goal that fits the state>" --no-open --out .private/mockos/survey/<app>/<state>
   ```

   That writes `raw.png`, `annotated.png` and `state.txt` (the state, and every item with its
   source, role and box), and prints the item, tree and off-screen counts with the timing.
   `--no-open` keeps it from opening the files.
6. Note in one line what the state is and how it was reached, in
   `.private/mockos/survey/<app>/notes.md`.

For timing:

7. For three to five ordinary actions per app (open a folder, open a menu, switch a pane, run a
   search, load a page), measure how long the screen takes to change and to hold still. A short
   supervised run does it: `uv run clicker "<goal>" --act --steps 3`, approved by the maintainer,
   whose `step-NNN-answers.json` holds each step's `settle`. Where run folders already cover the
   app, use those.

The survey does nothing that cannot be undone, and never on real data: no mail sent, nothing
deleted outside the scratch folder, no password typed. At a permission dialog it stops and asks.

### What the survey leaves

| Output | Where | Holds |
|---|---|---|
| Raw captures and notes | `.private/mockos/survey/` | Screenshots and screen text. Never committed, never quoted |
| A profile per app | `typesafe_computer_use/mockos/profiles/<app>.json`, written by `clicker-mock profile build` | Numbers only, per state: items, the split by source, the count per role, the share of controls with no label, repeated labels, off-screen controls, text lines, request bytes, the window's frame as fractions of the display, and timing percentiles. No label, no text, no image |
| An outline per app | The docstring of the mock app's module | Written by the builder in their own words: the regions (toolbar, sidebar, list, detail), the kinds of control in each, and the flows with their step counts. Ordinary control names (Back, Search, New Folder) are fine. Nothing from a content area |

Before a profile is committed, its diff is read: numbers and role names only.

### How the mock uses it

- **Build to the outline.** Each mock app has the real one's regions and flows, so a job takes the
  same number of steps.
- **Fill to the profile.** Default seeds give each screen the real density: enough rows, sidebar
  entries and toolbar buttons for the item count and the role mix to land near the profile. The
  kit lets a control go without a label, so an app can match the real share of unlabelled
  controls. Such a control reaches the loop only as whatever text it shows, as on a real screen.
- **Time to the profile.** The `typical` latency profile draws each app's delays from its measured
  timings.
- **Check it.** `clicker-mock profile check` puts each mock app into each surveyed state, reads it
  through the real `perceive`, and reports where a number is more than a quarter off the real
  app's. It asks no model. A phase is not done until its apps pass.

The survey needs the Mac. A builder working in a cloud session builds to a provisional density
(the Finder and Chrome figures above) and runs the check once the profiles exist.

## The adapter

`typesafe_computer_use/mockos/desktop.py`: `MockDesktop`, which provides the whole `Desktop`
surface over one CDP `Session`. It is added to the adapters `tests/test_platform_adapter.py` holds
to the protocol, parameter for parameter.

### The snapshot

`screenshot()` does three things in order: `MockOS.hold()` (flush pending renders, stop the
scheduler, return the snapshot as JSON), `Page.captureScreenshot`, `MockOS.release()`. The image
it returns carries the snapshot's id in its `info`.

Why hold the scheduler: the pixels, the text and the controls then describe the same instant. A
seeded delay that fired between two CDP calls would otherwise give the loop a screenshot of one
screen and the controls of the next.

Every query answers from the latest snapshot. Any input (a click, a key, typing, a scroll) marks
it stale, and the next query takes a fresh one first. `OSWorldDesktop` does the same with its
observation in hand.

### The surface

| `Desktop` call | In the mock |
|---|---|
| `screenshot`, `display_scale` | The snapshot above; scale 1.0 |
| `frontmost_app_and_pid`, `frontmost_window_bounds`, `keyboard_focus` | From the snapshot: the app in front, a fixed number per app, its window's frame |
| `focused_field` | The focused text control as a `Field`: role, label, placeholder, value, frame, caret and selected text. A password box is `AXSecureTextField` and its value is never read |
| `actionable_elements` | `ax_walk.walk_actionable` over the snapshot's tree (below) |
| `recognize_text` | By mode (below) |
| `browser_url`, `browser_tabs`, `show_tab` | The mock browser's tabs. `browser_url` gives the active tab's URL whenever the mock browser is running, whichever app is in front, as AppleScript answers on the Mac; `None` when it is not running |
| `installed_apps`, `activate` | The mock's apps other than the browser; `MockOS.launch` |
| `installed_browsers`, `default_browser` | None to choose between: the one browser is the run's own, as in `OSWorldDesktop` |
| `open_url` | `MockOS.browser.open(url)` |
| `click_at` | `Input.dispatchMouseEvent`: moved, pressed, released, with the button and click count |
| `drag` | Pressed at the start, several moves, released at the end |
| `press` | `Input.dispatchKeyEvent` with the modifier bits. Command maps to Meta, and the page treats Meta and Control alike. Command-[ is Back in the mock browser |
| `type_text`, `clear_field` | `Input.insertText`; select all and delete in the focused control |
| `scroll`, `hover` | A wheel event at the point, or at the window's center; a mouse move |
| `ax_press`, `ax_focus`, `ax_set_value`, `ax_value` | A DOM `click()`, `focus()`, setting the value and firing `input`, reading the value. Each refuses an element that is gone |
| `sleep_watching` | A real sleep |
| `check_abort`, `abort_hint`, `accessibility_trusted` | Nothing to check: the mock has no pointer of the user's. Ctrl-C stops a run |
| `open_path` | Not supported, as in `OSWorldDesktop` |

`ax_press` working is a choice. On the Mac an item that came from the tree is pressed through it,
and only falls back to a pointer click (`actions.click_item`). In the OSWorld VM nothing can be
pressed. The mock follows the Mac, since the Mac is where the project runs, and a site may mark a
control as answering only to pointer events, which exercises the fallback.

### Controls: the tree

The snapshot exports the front app's window (with any open menu, sheet or dialog) as a tree of
`{id, role, label, frame, press, children}`. Roles are mapped from the DOM to the names the Mac
uses, so `models.ROLE_WORDS` and `ax_walk.AX_ACTIONABLE_ROLES` apply as they are: `button` to
`AXButton`, `link` to `AXLink`, `checkbox` and `switch` to `AXCheckBox`, `textbox` to `AXTextField`
or `AXTextArea`, `searchbox` to `AXSearchField`, `tab` to `AXTab`, `menuitem` to `AXMenuItem`,
`row` to `AXRow`, a popup menu's button to `AXPopUpButton`, a closed menu to `AXMenu`, plain text
to `AXStaticText`.

The adapter hands that tree to `walk_actionable` with three small callables, as `osworld/a11y.py`
does for AT-SPI. Why reuse the walk: its pruning rules (off the display, slivers, closed menus,
nameless groups, the caps) are part of what the loop is, and a second copy would drift.

A control scrolled out of its pane is reported with a frame parked off the display, the way
Chromium parks one (`tests/world.py` does the same with `OFFSCREEN_Y`). The walk then lists it as
an off-screen control, which is what offers `press_offscreen`.

### Reading text

`--ocr` picks one of three ways: `dom`, `rapidocr`, or `vision`. In the default mode, `dom`, the snapshot lists every rendered line of text with its box: one entry
per line fragment of each text node, the value or placeholder of a text control at the control's
box, and nothing for an icon. Text that another element paints over is left out. A password box
gives dots. `recognize_text` returns the lines that fall inside the image it was handed.

Why this default: it is deterministic, takes a few milliseconds, and is the same on every machine,
which a comparison of cost and speed needs. An icon-only button still reaches the loop only
through the tree, as on a real screen. The other two modes hand the image to
`osworld.ocr.backend(name)` and are for the day someone wants to measure perception.

One thing needs solving. `perception.ocr_crop` crops the capture and calls
`desktop.recognize_text(crop)`, and the crop does not say where on the screen it came from. Two
ways to tell the adapter:

1. **Recommended: two lines in `ocr_crop`** that record the crop's origin in the crop's `info`
   (`crop.info["origin"] = (x1, y1)`). Pillow copies `info` into a crop, so the snapshot id set by
   `screenshot()` arrives too (checked on Pillow 12.3). Real OCR never looks at `info`.
2. **No change to `perception.py`:** `MockDesktop.screenshot()` returns an `Image` subclass whose
   `crop` records the origin itself. It works, and it rests on how the loop happens to crop.

The first is recommended because it is explicit and tiny. It is a change to the loop made for a
test harness, so it is the maintainer's call (see [Open questions](#open-questions-for-the-maintainer)).

## Tasks

`typesafe_computer_use/mockos/tasks/`, one module per app family. Tasks are Python, because a
check needs logic and a template needs a generator. They are synthetic, so unlike the cases in
`.private/evals/` they can be committed and quoted. **Nothing in a task may be copied from a real
run**: a failure seen in `runs/` may inspire a template, rewritten with made-up names.

```python
@dataclass(frozen=True)
class Task:
    id: str  # "files/rename@2": the template and the seed
    tier: int  # 1 to 4
    goal: str  # what a user would type
    seed: dict  # the state MockOS.load takes, including the clock and the app in front
    check: Callable[[dict, str | None], bool]  # the final state and the run's answer
    oracle: tuple[tuple, ...]  # the steps that solve it, as (kind, target), like tests/world.py's policies
    writes: tuple[str, ...] = ()  # what the scripted writer types, in order, for the oracle
    replies: tuple[str, ...] = ()  # what the scripted user answers when the writer asks a question
    steps: int = 30  # the step limit
    tags: tuple[str, ...] = ()  # the loop paths it exercises: "type_text", "scroll", "moves", "answer", ...
```

### Tiers

| Tier | Steps for the oracle | What it adds |
|---|---|---|
| 1 | 1 to 3 | One app, the target in view, one kind of action |
| 2 | 4 to 8 | Navigation inside one app: a search, a scroll, a small form, a dialog |
| 3 | 8 to 15 | Something in the way: repeated labels, a banner, a slow page, a dead link, several fields, an answer that takes comparing |
| 4 | 15 to 30 | More than one app, or a stop the writer has to settle: an ambiguous goal, a question for the user |

Difficulty comes from knobs a template sets, not from the app: the number of distractors, repeated
labels, a banner or dialog in front, a slow page, how far down the target is, whether text has to
be typed, whether the moves beyond clicking are needed, how many apps the task crosses, and
whether the answer was on an earlier screen.

**Tune the suite so the current agent solves roughly 70 to 85% of it.** Speed and cost are compared
over the tasks solved in both passes, as `scripts/osworld results` reports solved and failed tasks
apart, so most tasks must be solvable today; the rest are there to notice a shift in capability.

### Checks

A check is a predicate on `MockOS.dump()` and the run's answer:

- A task that changes something checks the state: where a file is, what a setting holds, what was
  sent. It also checks that nothing else changed, when a wrong action could do damage.
- A task that asks a question checks that the answer contains the value, with a plain string or a
  pattern. No LLM judges anything.
- A **trap** task has no right action (the goal names something that is not there). Its check
  passes when the state is unchanged and the run did not claim success.

Every row also records the writer's own verdict (`goal_achieved` in `run.json`) beside the check.
The pair gives a number no real run gives cheaply: how often the run said "done" and was wrong.

### Oracles

Each task carries the steps that solve it. `clicker-mock check` runs them through the real loop
with scripted stand-ins for both models. That gives three things for free:

- Proof that the task can be solved through the adapter, so a failed pass is the agent's failure
  and not the environment's.
- A check of the environment that asks no model, costs nothing, and can run in CI.
- The best step count, so a row can say "9 steps where 6 would do".

The stand-ins exist in `tests/world.py` (`FakeTypeSafe`, `FakeWriter`, `scripted`). They move into
the package, and `tests/world.py` imports them from there, so there is one copy.

### Starter list

About 45 templates. Each is one sentence here; the builder writes the seed, check and oracle.

| Id | Tier | The task | Exercises |
|---|---|---|---|
| `settings/toggle` | 1 | Turn a named switch on | `click_item` on a control from the tree |
| `settings/read-value` | 1 | Say what a setting holds | a read-only goal, the answer |
| `settings/popup` | 2 | Pick a value in a popup menu | a menu opened and read as items |
| `settings/search` | 2 | Find a setting by searching, then change it | `type_text`, submit |
| `settings/nested` | 2 | Change the option on one of several rows that all carry the same button | repeated labels told apart by row |
| `settings/radio` | 2 | Pick one of a radio group | |
| `settings/scroll` | 2 | A switch at the bottom of a long pane | `scroll_down`, `press_offscreen` |
| `settings/reset-confirm` | 3 | A reset that asks for confirmation | a sheet, `press_escape` on the wrong path |
| `files/open` | 1 | Open a named file | an Open button, or a double click when the moves are offered |
| `files/new-folder` | 2 | Make a folder with a given name | `type_text` with submit |
| `files/rename` | 2 | Rename a file | a context menu or a toolbar button, then typing |
| `files/trash` | 2 | Move a file to the Trash | a confirmation dialog |
| `files/move` | 3 | Move a file into a folder | `drag_item`, or the "Move to" dialog |
| `files/find-nested` | 3 | Find a file three folders down and say its size | navigation, the answer |
| `files/newest` | 3 | Say which file in a folder changed last | a sort, comparing dates |
| `files/restore-missing` | 2 | Restore a file that is not in the Trash | a trap: the right outcome is stopping |
| `shop/add-to-cart` | 2 | Put a named product in the cart | a web page, `press_showed` |
| `shop/search` | 2 | Search for a product and open it | `type_text` with submit |
| `shop/cheapest` | 3 | Take the cheapest of several like products to checkout | repeated "Add to cart", comparing prices |
| `shop/banner` | 3 | The same with a cookie banner over the page | a press reaches under it, a click does not |
| `shop/pointer-only` | 3 | A control that ignores a DOM click | the pointer fallback in `click_item` |
| `shop/form` | 3 | Fill a shipping form with a given name and city | several fields, no credential |
| `shop/newsletter` | 2 | Sign up with "my email" | `type_email` |
| `tickets/next-event` | 3 | Reach checkout for the cheapest ticket to the next event | date hints from `dates.py` |
| `tickets/slow` | 3 | A listing that takes a few seconds to load | `wait`, settle |
| `tickets/price` | 3 | Say what the cheapest ticket to a named event costs | an answer from an earlier screen |
| `wiki/fact` | 2 | Answer from an article, below the fold | `scroll_down`, a read-only goal |
| `wiki/dead-link` | 3 | The first matching link is dead | `go_back`, "already tried on this screen" |
| `browser/by-address` | 2 | From Files, open a site the goal names and do one thing there | `use_browser` with a URL the writer proposes |
| `browser/tab` | 3 | The page is open in another tab | `browser_tabs`, `show_tab` |
| `mail/who-sent` | 1 | Say who sent a message about a topic | the answer |
| `mail/flag` | 2 | Flag the message from a named sender | the same button on every row |
| `mail/search` | 2 | Find a message by searching | `type_text` |
| `mail/reply` | 3 | Reply to a message saying a given thing | a text area, the writer |
| `mail/compose` | 3 | Write a new message to an address with a subject | several fields |
| `calendar/whats-on` | 2 | Say what is on a given day | the answer |
| `calendar/create` | 3 | Create an event on a date at a time | a date picker, typing |
| `calendar/move` | 3 | Move an event to another day | editing, or a drag |
| `notes/new` | 2 | Make a note with a title and a line of text | a text area |
| `notes/append` | 3 | Add a line to an existing note | typing at the caret, nothing replaced |
| `notes/find` | 2 | Say which note mentions a thing | search, the answer |
| `cross/mail-to-calendar` | 4 | A message names a meeting; put it in the calendar | `open_app`, reading on one screen, typing on another |
| `cross/price-to-note` | 4 | Find a price on the shop and write it in a note | the browser, then an app |
| `cross/note-to-files` | 4 | A note says which file goes where; move it | |
| `cross/ask` | 4 | A goal that leaves a choice open, with a scripted reply | the writer's question |
| `cross/two-good-moves` | 4 | A goal where two first moves are both right | low confidence, the writer's focus, the hand-back |

No task ever needs a password typed (`CONTRIBUTING.md`: never add a path that types a password).
A pass uses a made-up address for `type_email`, never the maintainer's `CLICKER_EMAIL`.

## Passes

### Commands

```
clicker-mock list [--tier N] [--tag T]       the tasks; no browser
clicker-mock check [TASK ...]                run the oracles: no model, no batch
clicker-mock run [TASK ...] [--tier N] [--repeats N] [--jobs N] [--headed]
                 [--ocr dom|rapidocr|vision] [--latency instant|typical|slow]
                 [--no-cache | --cached-only]
clicker-mock compare PASS_A PASS_B           the differences between two passes; no browser
clicker-mock show PASS [TASK]                a pass's rows, or one run's summary; no browser
clicker-mock open TASK                       headed, seeded, left open to try by hand; prints the check on exit
clicker-mock replay RUN_FOLDER               write replay.html for a run folder; no browser
clicker-mock profile runs                    numbers per real app, from the run folders in runs/; reads files only
clicker-mock profile build SURVEY_FOLDER     numbers per real app, from a survey's captures; reads files only
clicker-mock profile check [APP ...]         each mock app's numbers against the real app's profile; no model
```

It is a command of its own and not a subcommand of `clicker-eval` because
`tests/test_import_boundaries.py` forbids `evals.cli` from reaching `platform_adapter` or
`perception`, and a mock run needs both.

### The cache

Decisions go through `EvalClient`, which caches each reply by its request and its repeat number.
The writer gets the same treatment: a small wrapper around `messages.create` that stores the reply
(its text and its usage) under a hash of the request.

What this buys:

- A pass on unchanged code sends nothing and costs nothing. It still runs the loop for real, so
  its timings for capture, perception and settle are real.
- A change pays only for the requests it changed, and for whatever new screens those lead to.
- Rows stay comparable: the cached reply keeps its recorded token counts, cost and latency, so a
  row says what the run **would cost live** whether or not this pass paid for it. A row carries both
  `cost` (as if live) and `spent` (paid by this pass), and both `model_seconds` (recorded) and
  `loop_seconds` (measured now, outside the model calls).

`--repeats N` asks each task N times with separate cache entries. It is there because the
classifier picks the same item for the same request only about 95% of the time (`OBSERVATIONS.md`):
a change that alters a request draws a fresh sample, and the difference between two passes is then
part change and part chance. A number counts only when it moves by more than the spread between
repeats, the rule `docs/improvement-loop.md` already uses.

The cache lives in `.mockos/cache/`. In practice it belongs to one machine: the answer model is
sent the screenshot, and pixels differ between a Mac and a Linux container even with the same font.
Decision requests carry no pixels and should hit across machines (verify).

### The budget

`AGENTS.md` already says it: a command that asks a model runs only inside a batch the maintainer
approved, with a dollar cap. `clicker-mock run` uses the same `Ledger`
(`.private/evals/ledger.jsonl`), checks it before every real request, and stops when the cap is
spent, keeping the rows it has. `check`, `run --cached-only`, `list`, `compare`, `show` and
`replay` ask no model and need no batch.

### What a pass should cost

Estimates, to be replaced by the first measured pass:

- **Decisions.** The README measures about $0.0002 a decision. Forty tasks of about ten steps is
  about 400 decisions: under ten cents.
- **The writer and the answer model.** `config.DEFAULT_HANDOFFS` notes that each stop costs "a few
  seconds and a few cents". With one to three stops a task, forty tasks is roughly one to three
  dollars, nearly all of it the answer model.
- **Time.** A decision takes 0.13 to 0.38 s (README) and a settle look is 0.25 s, so a step is
  about a second and a ten-step task ten to twenty seconds, plus a few seconds per stop. Forty
  tasks in sequence is then ten to twenty minutes with an empty cache, and a few minutes with
  `--jobs 4` or a full cache. At the 37 to 134 s a task recorded on OSWorld, forty tasks there are
  25 to 90 minutes of VM time.

### Rows

One JSON line per task in `benchmarks/mockos/<pass>.jsonl`, in the spirit of
`benchmarks/osworld/`: numbers and ids, and a file is part of the record once it is committed.

| Field | What it holds |
|---|---|
| `pass`, `task`, `tier`, `tags`, `repeat` | Which run of which task |
| `score` | 1 when the check passed, else 0 |
| `outcome`, `said_done` | Why the loop stopped, and the writer's own verdict |
| `steps`, `oracle_steps` | Actions taken, and the oracle's count |
| `seconds`, `loop_seconds`, `model_seconds` | Wall time; time outside model calls; recorded model time |
| `timing` | Mean seconds per phase, from `run.json`: capture, ocr, ax, decide, act, settle |
| `calls` | Per role (decision, reviewer, writer): requests, input and output tokens, cost |
| `cost`, `spent`, `sent`, `cached` | Dollars as if live; dollars this pass paid; requests sent and served from the cache |
| `handoffs`, `questions` | Trips to the writer and questions put |
| `models`, `settings` | The model id each reply named; the OCR mode, latency profile, and `CLICKER_MOVES` |
| `git_commit`, `git_dirty`, `chromium`, `machine` | What it ran on |

`clicker-mock compare` prints, for two passes: tasks solved in each and the ones that flipped; and,
over the tasks solved in both, the change in steps, requests per role, input tokens, cost, loop
seconds, settle seconds and model seconds, with the per-task lines for whatever moved. It warns
when the two passes ran different model ids, since `~typesafe/jev-latest` is an alias that moves.

### Watching

- **`--headed`** opens the Chromium window while the loop drives it. Input goes over CDP, so it
  does not use the maintainer's pointer or keyboard, but the window does appear and may take the
  focus when it opens. In the sandbox the window shows up in the noVNC tab `scripts/sandbox watch`
  prints.
- **`replay.html`** is written into every run folder from the files `runner.run_step` already
  writes (`step-NNN.png` with the pick marked, `step-NNN-answers.json`, the history line, the
  timing). One static page, arrow keys to step through. A pass also gets an index page listing its
  tasks with pass or fail. The command prints the path and opens nothing: on the Mac, opening a
  file is the maintainer's to do.
- **`clicker-mock open TASK`** leaves a seeded mock OS open for a person to click through. It is
  for writing tasks, and for seeing why an oracle fails.

### Where files go

| Path | What | In git |
|---|---|---|
| `typesafe_computer_use/mockos/` | The adapter, the page, the tasks, the commands | yes |
| `benchmarks/mockos/` | Pass rows, and a `config.json` naming the models a pass runs on | yes, by choice, as with OSWorld's |
| `.mockos/cache/`, `.mockos/runs/` | The reply cache and the run folders, in the main checkout (`store.checkout_root`), so worktrees share them | no: add `.mockos/` to `.gitignore` |
| `typesafe_computer_use/mockos/profiles/` | One file per real app: counts, shares and timings, with no text in them | yes |
| `.private/mockos/survey/` | Raw captures of the real apps: screenshots and screen text | no, never |
| `.private/evals/ledger.jsonl` | The budget, shared with `clicker-eval` | no |

Run folders are kept out of `runs/` so that `clicker-eval harvest` and `digest`, which read every
folder there, keep reading real runs only.

## Changes to existing code

Small, and each for a stated reason.

| Change | Why |
|---|---|
| `runner.run(cfg, ctx_factory, events=None, *, decisions=None)` | `run` builds `DecisionClient()` itself today, and tests swap it by patching the module. A factory argument lets a cached, budgeted or scripted client in without a patch. The default must still be looked up when `run` is called, so the tests that patch `runner.DecisionClient` keep working |
| `perception.ocr_crop` records the crop's origin | See [Reading text](#reading-text). Optional: there is a fallback that leaves `perception.py` alone |
| `browser/cdp.py`: `Chrome` takes extra command-line flags | The mock needs every host unresolvable, a forced scale factor, hidden scrollbars, and no throttling of a window that is covered |
| `FakeTypeSafe`, `FakeWriter`, `scripted` move from `tests/world.py` into the package | Oracle runs need them outside the tests. `tests/world.py` imports them back, and eight test modules import them from there |
| `tests/test_platform_adapter.py` lists `MockDesktop` | Every adapter is held to the protocol |
| `pyproject.toml`: the `clicker-mock` script | |
| `.gitignore`: `.mockos/` | |
| Docs: `docs/mock-os.md` (how to use it), `docs/layout.md`, a tier in `docs/improvement-loop.md`, "Read more" in the README | This plan is then deleted or kept as the design record, as the maintainer prefers |
| `AGENTS.md`: a short section on the mock OS | It restates how the unchanged rules apply: on the Mac a mock run launches a browser, so it needs a yes; in the sandbox, CI or the cloud it does not; a run that asks a model needs an open batch; `check` and `--cached-only` ask none |

## Tests and the machine guard

- **Unit tests, in pytest, with no browser.** The adapter against a fake `Session` that records
  calls and returns a canned snapshot. The tree mapping and the text-in-a-crop rule against
  snapshot fixtures. The task registry: unique ids, a check and an oracle on every task, the same
  seed giving the same state. Rows, `compare`, the writer cache, the budget.
- **The guard stays as it is.** `tests/conftest.py` already refuses `subprocess.Popen` and
  everything in `browser/cdp.py` that reaches a browser. The mock OS must reach Chromium through
  `browser/cdp.py` only, so the guard already covers it. Any other call that reaches the machine
  goes into the guard in the same change (`AGENTS.md`).
- **The environment check, outside pytest.** `clicker-mock check` launches Chromium and runs every
  oracle. It is what proves the page and the adapter work, and it asks no model.

## Build order

Each phase ends with something that can be checked. Stop and show the maintainer after phase 1.

| Phase | Build | Done when |
|---|---|---|
| 0. The seam | The desktop shell, Settings, `MockDesktop`, three Settings tasks, `clicker-mock check`. The `runner.run` argument and the moved stand-ins. `profile runs`, for a first set of real numbers | The three oracles score 1 in headless Chromium through `runner.run`; ruff and pytest pass; `test_platform_adapter` passes with the adapter in it; on the Mac, `profile runs` prints numbers per app |
| 1. Passes | `run` with the cache and the budget, rows, `compare`, `show`, `replay.html`, `--headed` | Inside an approved batch, a pass over the three tasks writes rows. A second pass at once sends no request and writes the same rows apart from measured time. `compare` shows no difference |
| 2. Files and Settings | The survey of Finder and System Settings, `profile build` and `profile check`. Then Files, the rest of Settings, their templates, the moves (context menu, double click, drag) | Every oracle passes; both apps pass `profile check`; a pass runs; the replay page reads well |
| 3. The browser | The survey of Chrome on the chosen sites. Then Chromium and the three sites, their templates | As above, and the banner, the pointer-only control, the slow page and the dead link each show their path in a run's log |
| 4. Mail, Calendar, Notes | The survey of the three. Then the apps, their templates, the cross-app tasks | As above, including one question to the user and one hand-back |
| 5. Record | The docs and the `AGENTS.md` section, the sandbox commands, an optional CI job, the suite tuned to 70 to 85% solved, a first baseline pass committed | A newcomer can run `scripts/sandbox run clicker-mock check` from the docs alone |

## Rules for whoever builds this

From `AGENTS.md` and `CONTRIBUTING.md`, as they apply here:

- **On the maintainer's Mac, ask before launching a browser**, every time, with the exact command.
  That covers `clicker-mock check`, `run` and `open`, headless or headed. In `scripts/sandbox`, in
  CI, and in a cloud session no approval is needed.
- **A run that asks a model needs an open batch**, with the cap and iteration count the maintainer
  named. Never raise, reopen or route around a cap.
- **Nothing from `runs/` or `.private/` goes into a commit, a pull request, an issue or a log.**
  Mock tasks are written from scratch.
- **The survey captures the maintainer's screen.** Every capture and every action on a real app is
  proposed and approved one command at a time. Raw captures stay in `.private/`; only numbers are
  committed. Nothing is read from inside an app bundle.
- **Tests stay off the machine.** Do not weaken the guard in `tests/conftest.py`.
- **Never a task that needs a password typed.**
- **Names.** Jev is the decision model. This project is System One Computer Use; do not call it
  jev in new prose. The mock OS is "the mock OS".
- Before a pull request: `uv run ruff check . && uv run ruff format .` and `uv run pytest -q`.

## Risks and what this cannot tell you

- **A mock is cleaner than a real app.** Text is read perfectly in the default mode and a press
  always lands. On the Mac, accessibility coverage runs from Finder's 100% to Spotify's none
  (`docs/how-a-step-works.md`). The profiles bring the item counts, the label coverage and the
  timings into line with the real apps, which narrows the gap and does not close it. A saving
  measured here is a claim. Confirm a change that matters with an OSWorld run or a supervised run
  before relying on it.
- **Seconds here are not seconds on a Mac.** Vision OCR is about two thirds of a real step and
  costs nothing in `dom` mode. The mock measures what the loop decides to do with time (how long it
  settles, how many looks, how many requests and stops), not what the machine takes to read a screen.
- **Fitting the loop to the mock.** If wording in `decide.py` is tuned until the mock's tasks pass,
  the number stops meaning anything. Keep templates varied, add seeds, and treat the suite as a
  guard for speed and cost work, not a target for capability work.
- **The cache can hide chance.** One cached sample is one sample. Use `--repeats` before believing
  a small difference.
- **Rendering.** Headed and headless Chromium, or two Chromium versions, may lay out a line
  differently. Rows record the Chromium version, and `compare` should say when two passes differ in it.
- **Parallel jobs and the cap.** `platform_adapter.using` is one adapter per process, so `--jobs`
  means several processes writing one ledger. Two could each pass the check and together overshoot
  the cap by a request or two. Keep a reserve per job, or start with one job.
- **Things to verify early, in phase 0:** that key and mouse events from CDP behave in headless
  Chromium as they do headed (focus, the caret, a right click raising `contextmenu`); that a
  covered headed window keeps rendering with the flags above; that the font loads from a data URI
  under `file://`.

## Open questions for the maintainer

1. **The two-line change to `perception.ocr_crop`**, or the adapter-only fallback?
2. **Vendoring**: one UI library file and one font file, each with its license, in the repository?
3. **A CI job that launches Chromium** to run `clicker-mock check` on every push? It asks no model,
   and it runs on GitHub's machine, not the Mac. (Moot for now: the repository has no CI since #38.)
4. **Which models a pass runs on.** `benchmarks/replay/config.json` fixes them for `clicker-eval`:
   Jev for decisions, and a free model for answers. A mock pass scores the writer and the
   hand-offs, so here the answer model is most of the bill and much of the result. For speed and
   cost work on the product itself, the mock should probably run what a real run uses. A
   `benchmarks/mockos/config.json` would fix it either way.
5. **Are pass rows committed as a matter of course**, or only baselines?
6. **The rule for keeping a change.** A suggestion, after `docs/improvement-loop.md`: keep a speed
   or cost change when no task solved in two of three repeats before is unsolved in two of three
   after, and the number it set out to move moved by more than the spread between repeats.
7. **The survey's data.** A separate macOS account with made-up content, or scratch folders in the
   maintainer's own account?
8. **Who drives the real apps during the survey**: an agent with computer use, one approved action
   at a time, or the maintainer by hand while the agent only captures?
9. **Which public sites** stand for the shop, the event listing and the reference article.

## Later

- **An LLM baseline.** The same tasks, through the same adapter, with a frontier-model agent, and
  the same rows: the comparison `VISION.md` is about, as `scripts/osworld run-luna` gives on OSWorld.
- **A live viewer page**, for watching a headless run in a cloud session.
- **A virtual clock.** `runner.settle` reads `time.monotonic` itself, so a pass cannot run faster
  than its waits. With a clock the adapter owns, sleeps could advance the mock's time without
  passing real time, and a pass would run at the speed of the CPU. It needs a seam in the loop.
- **A perception tier.** Real OCR in the record, and controls drawn on a canvas. Controls with no
  label are already in the first version, at the share the profiles give.
- **Cases from mock runs.** A solved task's steps are picks a state check stood behind, where the
  silver labels of `clicker-eval` rest on the answer model's word.
- **Scale 2**, to match a Retina display, and windows that move.

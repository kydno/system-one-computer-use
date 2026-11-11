# How a step works

A step reads the screen, adds the facts code can decide, asks the decision model one question in
three parts, and acts. This page follows it from the capture to the stop that ends a run. "The
classifier" below always means the decision model: Jev, TypeSafe's, by default, or another one
from [decision models](decision-models.md). The writer is a separate text model.

```
screencapture ─► Vision OCR ─► merge lines into blocks ─► drop lines echoing the goal
accessibility ─► actionable elements (role, label, frame), pruned to the display,
                 the labelled pressable ones it pruned kept as off-screen controls
                     │
                     └─► one numbered list of items, each carrying its source
                     │
accessibility ─► focused field (role, label, placeholder, value, frame)
AppleScript   ─► frontmost app and pid, active tab URL
clock         ─► local date and time
dates.py      ─► "dated 2026-10-13 (in 27 days)" on any block containing a date,
                 "near a line dated ..." on its neighbours, none from the menu bar's clock
layout        ─► "beside" (the row's other labels) on any label that appears more than once
runner.py     ─► the actions already tried on this same screen, each of which led back here
                     │
                     ▼
        one decision request, three Choices, plus one for off-screen controls
        and one when more than one browser is installed
        ┌────────────────────────────────────────────────────────────┐
        │ kind      : click_item | use_browser | open_app | scroll…  │
        │ item      : which item (click_item; where a scroll goes)   │
        │ site      : which website (used only for use_browser)      │
        │ browser   : which browser (used only for use_browser)      │
        │ offscreen : which hidden control (only for press_offscreen)│
        └────────────────────────────────────────────────────────────┘
        and, only when kind is open_app, a second request:
        app : which installed app, or none
                     │
                     ▼
        deterministic action ─► wait ─► next step
```

Items carry where they came from: `ocr` for a text block, `ax` for a control the app
declared, `ax+ocr` when both found the same thing. A symbol OCR reads off a button or
link, `←` on Back or `☆` on the bookmark star, is that control's icon, and the control
stands for it: two options for one click would only split the vote. An `ax` item has a
`role` (`button`, `menu`) in its row of the state's `screen_items_in_reading_order`, so the
classifier can tell a real control from a line of text. A label that appears more than once
carries its row as well, `"beside": ["Coldplay", "Oct 2"]`, since the label says nothing
about which and the layout does. Each item goes out once, in that list: the item question's
criteria are only pointers to its rows (`"14": "Item 14."`). They used to repeat every row, and the
two copies were 85% of a request; the copy in the criteria was 8.5 KB of 23.2 KB, and with a pointer in
its place a request is 26% smaller and its input tokens 17%, the same items picked (silver agreement
0.598 both ways on `~typesafe/jev-latest`). Dropping the state's list instead saves more and loses the kind
question the screen: agreement 0.446, `scroll_down` picked twice as often. Text read inside the focused one-line field is not an
item: it is the field's value or placeholder, the state carries the value, and the field
is an item of its own when the app declares it. A text area keeps its lines.

A control under a popup says which, in its row: `"under": "'Restore pages?'"`.
Chrome draws its bubbles, menus, and dialogs as windows of their own, in front of the page, so a
click on the page there lands on the popup. Picking such an item closes the popup first, with its
own close button, or with Escape when it has none, and never with its other buttons ('Restore'
reopens the last session), then clicks the item, in the same step. Only OSWorld's tree marks
these. A Mac or Windows item that came from the tree is pressed through it, which reaches the
control under a popup anyway. "Under", not "covered by": in a replay of 81 captured requests
from screens with a popup, "covered by" drew the classifier toward Escape and lowered its
confidence, while "under" left both as they were.

Splitting the decision into three questions keeps screen noise out of the action
choice. Every stall found while building this came from two options that meant the
same thing. Confidence measures concentration, so overlapping options always read as
doubt. Keep the action set mutually exclusive.

## OCR cost

Vision is about two thirds of a step, and it charges by the amount of text rather than
the number of pixels, so the only real saving is reading less of the screen.

- **Crop.** Each step reads the frontmost window with an 8 pt margin, plus the menu bar
  strip over the same columns, clamped to the display. Text on the desktop and in
  background windows is noise to the decision. Clipping the strip to the window's width is
  what makes the crop pay on a full-height window. The cost: the clock and the menu extras
  to the right of the window go unread. They stay clickable through the accessibility tree.
  The window is the one accessibility reports as focused, not the topmost one Quartz
  lists: Chrome in full screen draws its toolbar in a window of its own above the page's,
  and a crop cut to the topmost window read only the toolbar. Quartz's topmost window
  stands in when accessibility has no answer.
- **Reuse.** The capture is compared with the previous one at 1/8 scale, in 256 px tiles.
  Unchanged tiles keep the lines they produced last step. The changed tiles are clustered
  into blobs, sides and corners counting as touching, and each blob becomes a rectangle
  read on its own. Scattered change is the ordinary case, a clock digit plus one repaint,
  and one rectangle around both would span the display. Each rectangle grows until no known
  line straddles its edge, because a crop through a line returns the half it can see; ones
  that meet after growing merge, and more than four merge by closest pair down to four.
  Past 60% changed tiles, past 60% of the region in summed rectangle area, or on an app
  switch or a window move, the whole region is read instead.

The timing line says how much was read, and in how many pieces: `ocr 0.31s (22% of screen,
2 rects)`. A replay (`--image`) always reads the whole image and never reuses, so an offline
repro matches the original run.

## Accessibility tree

OCR cannot see an icon. The accessibility tree can, so each step also walks the frontmost
process for labelled, on-screen controls. Coverage is uneven, measured on ten apps on one
Mac: Finder 100% of on-screen controls labelled, Chrome 88%, Slack 85%, Notion 68%,
Spotify 0 (its CEF shell exposes three window buttons and nothing else). Terminals expose
the grid as one text area. So AX is a bonus source, never a replacement.

Labels live in `AXDescription` for web and Electron, `AXTitle` for AppKit, and a short
`AXValue` otherwise. A decorative image takes the label of the control around it; a list
row takes it from a shallow `AXStaticText`.

Frames lie, so the walk prunes hard:

- skip any subtree whose real frame misses the display (Notes reports rows 200 screens
  down, Chrome parks scrolled-out nodes above the viewport)
- skip any node under 4 pt wide or tall (Chromium clamps scrolled-out web nodes to slivers)
- skip `AXMenu` subtrees, which are thousands of zero-sized items behind a closed menu
- skip nameless `AXGroup` layout boxes, even pressable ones
- stop at 4000 nodes or 0.6 s and say so

Walks measured here: Finder 152 controls in 0.08 s, Chrome 172 in 0.59 s. The assistive
handshake attributes (`AXManualAccessibility`, `AXEnhancedUserInterface`) are unsupported
on this macOS, so nothing relies on them: Brave answers a set of the first with -25205.

The focused field is asked of the whole system first, and of the frontmost app when the system
cannot say. The system-wide question can fail at once with -25204 for every app, whichever is in
front, while the app asked itself still names its focused element. The step line then shows
`keys='no app (-25204)'`, from the app the system says holds the keyboard; it shows `keys=` only
when that is not the app in front.

A Google Doc takes its keys in a hidden 625 × 1 pt box and draws its text itself. The box is a
bare `AXGroup`, and counts as an editor when the browser names an `AXEditableAncestor` for it.
Brave names none, but the box's DOM id starts with `docs-texteventtarget`, as it does in Sheets
and Slides, and that counts too. Typing into an editor goes in by keystrokes at the caret, and
the screen is read to check it.

A Chromium browser that keeps its page out of accessibility can also report no focused element
at all, so a click into a text box reads as a click on nothing. On the screen right after a
mouse click on page text, in the same browser on the same page, the box the click landed in
stands in for the focused field when none is reported. The classifier is told it may not be a
text box, and the stand-in is left out of the screen's signature, since it is the last click
and not something the screen showed.

### Off-screen controls

`AXPress` does not need an element to be visible. Notes selects a row parked thousands of
points below the display, Chromium delivers a click to a link it clamped to a 1 px sliver
because the page is scrolled past it, and an auto-hidden Dock hands over all 37 of its
items from 5 pt below the bottom edge. So the same walk keeps the labelled, pressable nodes
it pruned, and offers them as a separate capped list rather than mixing them into the items:
nothing on the capture points at them, and a mouse click would land somewhere else entirely.

The list is deduplicated by role and label, drops any label the visible items already carry,
and stops at 120 controls, after which those subtrees are pruned as before, so the walk costs
what it always did. It is offered only when it is not empty, as a `press_offscreen` action
plus an `offscreen` question, and the step log counts it next to `ax=`. A refusal is the end
of it: there is no pixel to fall back on, so it reads as a no-op. What a walk finds depends
on the app, and the node and time caps bind first on a big tree: Notes and Chrome spend all
4000 nodes on what is already on screen and report nothing hidden.

## Action space

| key | does |
|---|---|
| `click_item` | press the element through the accessibility tree when the item came from it, so the press lands on the control rather than on whatever covers it; a mouse click at the center of the box otherwise, and as the fallback when the press is refused or, on a web page, when 0.4 s later the screen shows no change outside the focused field and the menu bar (Chromium accepts presses that pages listening for pointer events ignore), after closing the popup in front of it when there is one |
| `right_click_item`, `double_click_item`, `select_item_text` | (offered only to a run whose goal needs the moves beyond clicking and typing, with the item question's wording widened to match) a right click, a double click, or a triple click (which selects the item's line or paragraph) at the center of the item the `item` answer names; they reuse the `item` question and add no request. Always a pointer click, never an accessibility press, since a press is a single left click; a popup in front of the item is closed first, as for `click_item`. The menu a right click opens, or the file a double click opens, is read as ordinary items at the next step. A split on the item lowers the step's confidence as it does for a click, and a read-only goal's lower floor does not apply to them. Code refuses a double or triple click on an accessibility button, link, checkbox, radio button, pop-up, menu or tab, since a second click would submit twice, toggle a checkbox back, or land on the next page (`'Buy' is a button, one click activates it`); a right click is allowed there. The triple click is for copying: copying the selection is the `copy` shortcut. Typing does not replace a selection (a text area is typed into at the caret, a single-line field has its whole value set), so the kind's wording does not offer it for replacing |
| `drag_item` | (offered only to a run whose goal needs the moves beyond clicking and typing) press the left button on the item the `item` answer names, move to the item the `target` answer names in twelve steps, each with a look at the abort corner, and release there; a drag that is interrupted or aborted half way goes back to where the item was taken and lets go there, so nothing is dropped on what the pointer passed over (the abort corner has no side effect). Offered only when two items are on screen. The `target` question is a request of its own, sent only once `kind` is `drag_item` and the dragged item is not under a popup, with the state's items and every item but the dragged one and those under a popup as choices; with none left it is not asked. The `item` answer of a drag is the item that is taken. Refused when either item is under a popup. The step's picture marks the drop target in purple beside the red item taken. A split on any of the three answers lowers the step's confidence, since a drag moves things. Not for a slider or a map: a drag goes from one item to another, not by an amount |
| `press_offscreen` | `AXPress` a labelled control the app exposes but does not show, chosen from the off-screen list; offered only when that list is not empty, and a refusal counts as a no-op since there is no pixel to fall back on |
| `use_browser` | go to the browser the `browser` answer names, showing the website the `site` answer names: `none` brings it forward on the page already open there, a `SITES` catalog key opens that URL through AppleScript `open location`, and `other` opens a URL the writer proposes. The `browser` question lists the default (`$CLICKER_BROWSER`, else the browser macOS opens links in when it is one of these, else Chrome) and every other installed browser (Chrome, Brave, Edge, Arc, Chromium on macOS), each marked as the app in front now or the default; with only one, no question is asked and that one is used |
| `open_app` | bring the app the `app` answer names to the front, starting it when it is not running, with up to 10 s to get there. The `app` question is a request of its own, sent only once `kind` is `open_app`, since the list is long and most steps open no app: it carries the goal, the focus, and the app in front, and lists every app bundle in `/Applications`, `~/Applications`, `/System/Applications` and the `Utilities` inside each, except the browsers `use_browser` reaches, plus `none`. `none`, or the app already in front, is refused in the history line. Offered only where the adapter lists apps: macOS, not Windows or the OSWorld VM |
| `type_text` | the writer composes the string; it is set on the focused element through the accessibility tree, with keystrokes as the fallback when the value does not read back, and a Noul then checks the field's value; text the writer submits gets Return at once instead, and the next screen is the check. Into a stand-in field (see above) the text goes by keystrokes, and the Noul checks the text OCR reads across the box's row instead of a value. Into a rich-text editor that is no form field, such as a Google Doc (a focused element with an `AXEditableAncestor` and no text role), the text goes in at the caret by keystrokes, never after Select All and Delete, and the Noul checks the screen lines that share a word with it |
| `type_email` | fills in `$CLICKER_EMAIL` the same way; refused unless a text field is focused |
| `press_shortcut` | (offered only to a run whose goal needs the moves beyond clicking and typing; see below) press the shortcut the `shortcut` answer names, from the catalog `SHORTCUTS` in `config.py` (copy, cut, paste, select all, undo, redo, save, save as, find, new tab, reopen the closed tab, close tab, next and previous tab, address bar, bookmark, new window, open a file, print, reload, zoom in and out, bold, italic, underline, and the plain navigation keys: Tab and Shift-Tab between fields or cells, the four arrows, Page Up and Down; nothing that quits, logs out, or types), each written for a Mac and turned by the adapter into the keys of its platform (Command is Control on Windows and in the OSWorld VM). The `shortcut` question is a request of its own, sent only once `kind` is `press_shortcut`, and lists the catalog plus `none`; `none` is refused in the history line. The follow-up is sent the goal, the guidance, the frontmost app, the focused field (with its `selected_text` when the element says what is selected) and the last eight history lines, so a goal that takes select all, then copy, then paste is asked what is still to press. Unlike an app, a wrong shortcut is not always undone (cut, close tab), so a split on the shortcut answer lowers the step's confidence as a split on an item does, and a read-only goal's lower floor does not apply to it: a shortcut needs `min_confidence` whatever the goal. Code refuses, with the reason in the history line, a browser shortcut (new tab, reopen the closed tab, close tab, next and previous tab, address bar, bookmark, reload) when the frontmost app is not a browser (`BROWSER_APPS`, or the configured one), since the same keys close a document or reply to a mail elsewhere, and paste or cut when the focused field is a secure field or its label or placeholder names a password, code or card. What the keys did shows on the next capture; a copy changes nothing on screen, and the idle count bounds a run that only copies |
| `press_enter`, `press_escape` | keyboard |
| `go_back` | Cmd-[, the browser's Back, when the last click led somewhere unhelpful |
| `scroll_down`, `scroll_up` | 10 lines, after parking the cursor over the item the `item` answer names, since a wheel scrolls whatever is under it: on Google Maps the window's center is the map, which zoomed out while the results list beside it stayed put. With no item, or one in the menu bar or outside the frontmost window, the cursor goes to the window's center. 0.4 s later the screen around the cursor is compared with the capture, and a scroll that changed nothing there says so in the history (`scrolled down over 'X' (nothing there moved)`) |
| `wait` | screen still loading: 3 s, then the step's own settle, so three waits cover a slow page |
| `done`, `none` | stop |

### Moves beyond clicking and typing

`press_shortcut`, the right, double and triple clicks, and `drag_item` are in the kind question only for a run whose goal needs them. Once a run, before
its first step, the decision model is asked of the goal alone whether reaching it needs a move that
clicking and typing cannot make (`decide.needs_moves`, a Noul like the read-only question), and the
run is offered the moves when the answer is at least `MOVES_NOUL` (0.5). Unsure, or no answer, offers
none, so the requests stay as they were. The reason is measured: with `press_shortcut` in the kind
question of every step, agreement with saved steps that never needed it fell 2.6 points (0.601 to
0.575 over six repeats), mostly steps where the model moved off `scroll_down` to a click, not steps
where it picked the shortcut. A probe of Jev scored 20 goals that need one 0.58 to 0.98 and 16 that do not
0.05 to 0.36. The answer model's instructions follow the gate: it is told the agent has the shortcuts only
when the run was offered them, so it does not send the classifier to a move it lacks. The run records
`moves` in `run.json` and the log. `clicker-eval size` and `decisions` ask each saved step as its own run
was asked, with the moves when its run was offered them; `--moves` offers them in every case and
`--no-moves` in none. A saved pass says which: `moves_mode` (`own`, `on` or `off`) and `moves_cases`, how
many of its cases were asked with them.

`CLICKER_MOVES=on` offers every run the moves and `off` offers none, whatever the goal says, and
neither asks the decision model about the goal (one request fewer). `auto`, or nothing, is the gate
above. The setting exists for a benchmark that must run the same tasks with the moves in and out of
the kind question, without the gate's one-call guess deciding for it; a value other than these three
stops the run rather than quietly asking. `run.json` says who settled it, `moves_by`: `gate` or
`CLICKER_MOVES`.

A selection leaves nothing on the screen the request reads, so a run offered the moves is told what is
selected: the focused field's `selected_text` (the accessibility value of the selection, up to 200
characters, left out when nothing is selected, and never sent to a run that was not offered the moves).
Only the Mac adapter reads it so far; Windows and the OSWorld VM leave it empty, so there a selection is
still invisible to the request.
The clicks land on the middle of an item, and OCR reads close lines of a document as one block, so
"the second line" was out of reach: a run offered the moves keeps the lines of the focused text area apart
(`perceive(..., apart=True)`), one item each, and every other run reads the blocks it always did. A word
inside a line is still not an item.
The `shortcut` follow-up gets the previous actions and the focused field as well as the goal, and is told
that a goal can take several shortcuts in turn: without them it answered "select all" six times in a
row on a goal of select all, copy, paste, since the goal was all it saw.

After any action the screen gets time to settle before the next step reads it. It is looked at
every 0.25 s: once it differs from the capture the action was decided on and then holds still for
one look, it has settled. One that has not changed at all, or never holds still, gets the whole
`--delay` (2 s). The menu bar clock and a caret blink do not count as change. The step's timing
line shows the wait as `settle`. On Google Flights the fixed 2 s was 20 s of a 116 s run.

## Where free text comes from

The classifier never generates text. The writer model runs in three places, each with a
small packet and a structured reply. Each packet also carries the current focus and what
the user said, once there are any:

- **`type_text`** receives the goal, recent actions, the focused field's label and
  placeholder, the OCR lines near the field, and the text of the distinct screens the run
  passed through before this one, since what a goal says to write down (a fare, a name) was
  usually read on another page. It returns `{fill, text, submit}`. Credential
  fields come back `fill: false` and nothing is typed. The text is set as the field's
  value where the element accepts one; otherwise the field is emptied and the text
  typed, since keystrokes land after whatever it already holds. A document editor is never
  emptied: the text goes in at its caret. After typing, a Noul
  scores whether the field now holds a sensible value. Under 0.5 the field gets back
  the value it had before, set through the same element, and only while it still holds
  exactly the text just typed. When the element refuses the value, is gone, or holds
  something else by then, the unverified text stays in the field and the history line
  says so. Recovery never presses keys: the focus may have moved to another field.
  `submit` is for a name or value the goal says to create, rename, change, or save, or a
  search it says to run. Then Return follows the text and nothing checks the field, since Return
  usually takes it away; the next screen shows whether it took. A text area never gets
  Return: there it starts a new line.
- **`use_browser`** with `site: other` receives the goal and returns `{ok, url}`.
  Code rejects anything that is not a clean https URL with a hostname.
- **The answer**, each time the classifier stops. It receives the goal, every action
  taken, why the run stopped, the earlier stops with the focus given at each, whether
  anybody is at the terminal to be asked, the text of the last screen, the capture itself, because
  OCR misreads a letter here and there and drops layout, and the text of the distinct
  screens before it, newest first up to 600 lines, because the goal may ask for a price
  that was on the listing and not on the checkout. It returns `{achieved, answer, focus, question}`,
  and is told to take the answer from those screens and the user's replies alone, to give a focus
  as one move and not a plan, and only a move the agent has: a keyboard shortcut only from the
  catalog, a right click, a double click, a triple click on an item, or a drag of one item onto another, and only when the run was offered them (typing replaces what a field holds), and a website only by its https address. It
  never asks for a credential, and when the run ends short of the goal it says what the agent
  could not do. When an action ran after the last capture, the screen is captured again first.
  This one call uses `CLICKER_ANSWER_MODEL`, a stronger reader than the per-step writer.

Passwords are never typed. Rely on the browser's password manager or an SSO button
the OCR can read.

## Stopping a live run

Ctrl-C when the terminal has focus, or slam the mouse into the
top-left corner of the screen from any app. The corner is checked before every click, key,
scroll, app switch and accessibility action, and between typed characters, so a run stops
mid-word. A key or mouse button goes back up even when Ctrl-C lands between its down and
its up. The loop also stops itself on `done` or `none`, on confidence under
`--min-confidence` (0.4), when it stalls, or at `--steps`. Each of those stops goes to the
writer, which answers and may hand the run back (below).

Two things let a click through under that floor. A goal that only asks to find something out
("confirm the BigQuery export is on") clicks down to `--read-only-confidence` (0.15): the
decision model is asked once, at the start, whether the goal changes nothing, and a wrong
click on such a run only opens the wrong page. And a click the writer's focus quotes goes
ahead whatever the item's confidence, as long as the action itself clears the floor and no
other item of the same text comes within half its odds: two models agreeing on one item is
what the floor stands for. GPT-6 Luna spreads an item's odds over every item on screen, and
gave its right click 0.11 to 0.24 on three Firebase and Cloud Console runs.

## Stalls

Nothing in an action's description says what came of it; only the next capture
does. So each step keeps a signature of the screen (the app, the page, the text on it) and
the loop stops after three actions in a row that left the screen as it was (a refused
action, a wait on a page still loading, a scroll that has run out of page) or after two in a
row that were already taken on the same screen earlier in the run (a click that does
nothing, or a cycle through two pages), or after three navigations in a row to the same place
(`use_browser` or `open_app` that ends in the same line as the one before, which no reading of the
page can hide, since a site that answers with an error page reads a little differently each time).
Two captures count as the same screen when at most
one line differs, and that one is one line in ten or fewer: a clock or a ticker does not
hide a stall, and a two-line modal on a dense page is not mistaken for nothing happening.
The memory figure Chromium adds to a tab's name ("Settings - Memory usage - 56.0 MB") is left
out of the comparison, since it drifts between two captures of one screen.
When more than that changes every step, a run that is getting nowhere runs to `--steps`:
the rules err toward running on, never toward stopping a run that is making progress.

## The answer

When the classifier stops, the writer reads the screen it stopped on
and prints the result: the information the goal asked for, or where things stand and
the next step when the screen does not hold it. A dry run that would have acted, and
an aborted run, print no answer.

## The hand-off

A stop is not the end when the goal is not reached. One sentence of
goal does not say which of two good moves comes first ("cheapest, and here in under a
week": open the cheapest listing, or filter by delivery?), and a classifier split
between them reads as low confidence. So the writer's answer may carry a **focus**,
one move in terms of the screen ("Click the 'Arrives in 2-4 days' filter"), and the
classifier goes back to work with the goal and the focus both in its state, until it
takes an action other than a wait under it: a focus is one move, and kept past it, it
sent the classifier back to that move from every screen after. On the
capture that stopped such a run at 0.39, the same classifier picks the filter at
0.92 under that focus. It may instead carry a **question**, put to you in the terminal
when there is something only you can say ("13 or 15 inch?"); your reply joins the
state for the rest of the run, the writer reads the screen again with it, and the app
you were in comes back to the front. An empty reply declines, and the answer stands.
Or it may say the screen is still **loading**: a classifier shown the half-drawn Cloud
Console ranked a click on the menu over a wait, at 0.32, so the run waits itself, as a wait
the classifier chose would, and the classifier reads the screen once it has loaded.
The writer never picks a click: every action is still the classifier's.

The exchange cannot go round on itself. A focus the classifier takes no action under
leaves the answer it came with standing, without a second reading of the same screen. A
screen that changed on its own since that answer, as a page finishing loading does, is read
again: the answer describes a screen that is gone.
`--handoffs` (10) bounds the trips, three questions bound the asking, and a stop on
the last step is final. So is a third stall with no new page since the first: two focuses
did not free the classifier, so the run ends `stuck`, and the writer's answer says what
the agent could not do. On OSWorld's Chrome tasks every run that stalled a third time on
the same pages failed anyway, up to 210 s later, and no solved run stalled more than twice.
A `done` the writer does not see on the screen is sent back like any other stop.

## Who did the work

Every run ends by counting the requests each model took:

```
calls: classifier 14 (82%, 3.9s)  writer 3 (18%, 21.4s)  handoffs 1  questions 0
```

The classifier's share is the number the design stands on. A task it falls on is a
task the writer had to steer at every turn, and the fix belongs in the state the
classifier reads, not in more hand-offs.

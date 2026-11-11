# Improvement log

One entry per iteration, kept or not: the cluster of failures it took on, the hypothesis, the change,
the numbers before and after, and the verdict. Runs are named by counts, not by goal or screen text.

## 2026-11-10: the pinned decision model is Jev

`config.json` named `inception/mercury-decide`. OpenRouter lists that model, and its `:free` variant, with
no serving endpoints, and a request for either answers 404 ("No endpoints found"); the last run that
used it worked on 2026-11-05. The pass is pinned to `~typesafe/jev-latest` instead, the project's default
decision model, which answered a test request on the same endpoint. Every row records the concrete
model the replies named, since `jev-latest` moves. Rows before this change have no baseline to compare
with: there are none. Move the pin back when Mercury Decide has endpoints again, and take a new
baseline on the model you then run, because a row on one model is not comparable with a row on another.

## 2026-11-10: baseline on Jev (batch1, before any change)

107 silver cases (picks of runs the answer model judged achieved) x 3 repeats on `~typesafe/jev-latest`,
321 asks, $0.14 (about $0.00045 an ask, 10.7k input tokens an ask). Row: `20261110T205406Z.jsonl`.

- Silver agreement 0.60; 63 of the 107 cases were right in at least 2 of 3 repeats.
- Of the picks that were wrong, 32 were above the 0.4 floor (confident and wrong); of the picks that
  were right, 27 were below it (right but stopped as low confidence).
- The model picked the same action in all three repeats for 0.87 of the cases. The noise band is
  therefore about 13%, not the 5% assumed from Mercury Decide: a change counts only when it moves a
  number by more than that, or when its gold cases flip in at least 2 of 3 repeats.
- Cases mostly wrong, by what the run did against what Jev picked: 14 `click_item` with another item
  of the same kind; 9 where the run scrolled or went back and Jev said `done` or `press_escape`; 8
  where the run said `done` and Jev wanted to act; the rest are single cases.
- Silver is the earlier run's pick, made by whatever model ran then, so a miss here is a question
  and not yet a failure: gold labels on the failure points decide which side was right.

## 2026-11-10: iteration 1 of batch1 (no change kept)

Cluster: the first stop of each run that fell short, in the two largest groups: 18 low-confidence stops and
16 where the classifier answered "nothing helps".

- 19 of the 34 happened before 2026-10-30 16:00, when document-editor support landed (`b94e6d4`). Five are
  one case: a document just created has the keyboard focus but no field is reported, so `type_text` read as
  not valid and the run ended "nothing helps". The loop reports that case now; the saved screens cannot
  show it, because they hold no live field.
- 15 happened since. I read 8 closely: five are one vague goal on a tab that was already open (the kind
  probabilities spread over five or more actions with the top at 0.21 to 0.39, and the answer model's focus
  then picked the right tab, so the hand-off worked as designed), one is a dialog on another vague goal, one
  is an icon-only control that the answer model found from the image (an ability gap, not a fault of the
  loop), and one is an item pick at 0.11 confidence among several cards. None was a fault I could reproduce.
- The answer model sent back 45 of 62 `done` claims, 28 of 32 since 2026-10-30; the confidence of those sent
  back had a median of 0.85, of those accepted 0.99. The loop already reviews every `done`, so a false `done`
  costs one free reviewer call, not a run. Not changed.
- 14 baseline cases where Jev clicked another item than the run did: 13 of 14 are a different control, not the
  same one under another index, and in 12 of the 14 the run's item was read by OCR alone.

Verdict: nothing to change on this evidence, and a change made on it would be a guess. Evidence for a fix has
to come from fresh runs of specific goals on the current code. Added `digest --since` so the next look leaves
out runs from before the last change to the loop.

## 2026-11-10: iteration 2 of batch1, a stall that no rule counted (PR 24, kept)

A supervised run on a goal the browser's account blocked opened the same URL four times before it was
stopped by hand. The repeat rule counts actions already taken on the same screen, and an error page reads a
line differently each capture, so every open looked like a first. `runner.repeating` now counts navigations
(`use_browser`, `open_app`) whose history line equals the one before, and ends the run as `stalled` on the
third. Scenario `l32c` fails before and passes after. Against the 118 acting runs on disk, 5 hold three or more
identical navigations in a row and none was judged achieved, so no run that worked would have been cut. The
request to the decision model is unchanged, so there is no pass for it.

## 2026-11-10: iteration 3 of batch1, moves beyond clicking and typing (kept behind a gate)

Cluster: not a failure cluster but a gap in what the agent can do. It has no keyboard shortcut, right click,
double click, text selection or drag (issues #7 to #10), so a copy-and-paste, a context menu, a file moved
between folders or a reordered tab is out of reach. Built: `press_shortcut` (a catalog of fifteen),
`right_click_item`, `double_click_item`, `select_item_text` (a triple click), `drag_item`.

Offline numbers (`~typesafe/jev-latest`, silver cases, none of which needs such a move, so a pick of a new kind
can only count against it):

- Offered on every step, `press_shortcut` alone, 6 repeats against 6 repeats: silver agreement 0.601 (sd 0.014
  between repeats) to 0.575 (sd 0.010). Not noise: the drop is as large in the cases from after 2026-11-01
  (0.476 to 0.405 over 21 cases). Of the 14 pairs lost in the first three repeats only 2 went to a shortcut;
  the rest were the model reshuffling when the kind question grew (`scroll_down` picks 134 to 108, mostly to
  `click_item` and `press_escape`). The 12 shortcut picks came from two steps of one run; the follow-up
  question answered `none` each time, at 0.3 to 0.4.
- Every step was paying for a move almost none of them needed, so the moves are offered only to a run whose goal
  needs them: once, before the first step, the decision model is asked of the goal alone (a Noul, like the
  read-only question). A probe: 20 goals written to need a move scored 0.58 to 0.98 (median 0.93), 16 that do
  not 0.05 to 0.36. Of the 69 distinct goals in the saved runs, 13 score 0.5 or more (threshold `MOVES_NOUL`);
  by eye these are mostly tab and drawing tasks. $0.002.
- Gate closed (any other run): `clicker-eval size` reads +0.0% in every part, and all 642 requests of a
  six-repeat pass are already cached, so the baseline is reproduced exactly for $0.
- Gate open, all four kinds offered: request bytes +7.0% (kind question +72%, item question +1%), input tokens
  an ask +3.8%. Silver agreement 0.564 against the baseline's 0.598 on the same three repeats; the only new
  kind picked was `select_item_text`, 6 of 321. Row: `20261110T220134Z.jsonl`. That is the cost to a run the
  gate opens for, and about 3.4 points on steps that needed none of the moves.

Not measured, and it cannot be offline: whether the moves work. The saved screens do not react, no saved step needs
a shortcut or a drag, and the Quartz right-button, click-state and drag paths have never run on hardware. The
proof is supervised runs, which are the maintainer's to approve one command at a time.

Verdict: kept behind the gate. If the supervised runs show the gate opening on goals that do not need a move, or
staying shut on ones that do, `MOVES_NOUL` and the question's wording are the two things to move.
Spent so far in batch1: $0.73 of $4.00, three of three iterations.

## 2026-11-10: iteration 1 of batch2, the first supervised runs of the moves (kept)

Four runs on this Mac, each approved by the maintainer (a copy-and-paste in a plain-text document, a right
click, a triple click, a double click; the drag run was not approved and has not been run). Run folders
`20261110-171443`, `-171546`, `-171626`, `-171713`.

What worked on hardware, for the first time: the goal gate opened on all four (0.82 to 0.98), a Command chord
reached the app (the text shows selected in the next capture), the Quartz right button opened a context menu
(items 18 to 29) and Escape closed it (judged achieved), a triple click selected one line and a double click one
word, so the click-state counts are honored.

What did not:

- Select all was pressed six times over two runs (steps 1 to 4, then 6 and 7 after a hand-off). The shortcut
  follow-up was sent the goal and the app and nothing else, so its answer could not change after the first press,
  and a selection leaves no trace on the screen the request reads. The repeat rule stopped each run; nothing was
  lost, but the goal was never reached. Triple and double click repeated the same way, three or four times.
- Both clicks land on the centre of the item picked, and the item was one block of three lines, so the line and
  the word that were selected were the ones at its centre, not the ones the goal named. Aiming inside an item (a
  word, a line) is a gap the moves leave open.

Change: the shortcut follow-up now carries `previous_actions` and the focused field, and a field for a run offered
the moves reports the text selected in it (`selected_text`, from the field's accessibility value; absent when
nothing is selected, so a run without the moves sends the request it always did). The shortcut question tells the
model that a goal can take several in turn and to choose the next one still to press. Offline, on the saved steps
with the selection put back as the screenshot shows it, 3 repeats each: after one or two select-alls the follow-up
picks `copy` 6 of 6 at 1.00, where the live runs picked `select_all` 6 of 6. For the clicks the pick stays the same,
which is right on this evidence: the selected text was not the line or word the goal named, so the model could not
tell the goal was met; that needs the aiming above. Not measured: a copy-and-paste carried through on hardware with
this change, which needs another supervised run.

## 2026-11-10: iteration 2 of batch2, each item goes out once (issue 12, kept)

Cluster: cost, not a failure. A request holds every item twice, in the state's `screen_items_in_reading_order`
and in the item question's criteria, 85% of the body on 827 saved requests (23.2 KB a request, the two lists
10.4 KB and 8.5 KB). Three variants on the 107 silver cases x 3 repeats on `~typesafe/jev-latest`, against the
current code (agreement 0.598, 63 cases mostly right, 32 confident and wrong, 10,661 input tokens an ask):

| variant | request bytes | input tokens an ask | cost an ask | silver agreement | confident and wrong |
|---|---|---|---|---|---|
| the state's list dropped | -44.7% | 5,548 | $0.000233 | 0.446 | 80 |
| criteria "Item N in screen_items_in_reading_order." | -11.0% | 9,707 | $0.000408 | 0.604 | 28 |
| criteria "Item N." (kept) | -26.2% | 8,836 | $0.000371 | 0.598 | 28 |

- The state's list cannot go: the kind question reads the screen from it. Without it `scroll_down` is picked 124
  times in 321 against 67, `click_item` 50 against 108, and 48 cases are mostly right instead of 63.
- The criteria can: they only repeated what the list holds (text, region, the role the app declared, a date, the row
  a duplicate shares, a popup over it). The short pointer picks the same items: agreement is identical, the kinds
  picked differ by two, and confident-and-wrong picks fall from 32 to 28 (right-but-below-the-floor 27 to 24).
  Same pick in all three repeats 0.860 against 0.869, inside the noise band.
- The item question's instruction is unchanged, so the pass measured the code that is kept. It still says items are
  "marked with a role"; the role is in the state's rows. Rewording it is a separate pass.
- Only Jev was measured. Another decision model (see `docs/decision-models.md`) may read the pointer worse, and
  would need its own pass before it runs on this.
- Every saved case's item criteria now differ from what it was sent with (`clicker-eval check`: 0 of 827 exact; the
  state matches), as the wording changed on purpose. The old baseline row compares on bytes only through `size`.
- The drag target question uses the same pointers; no saved step needs a drag, so only the scenario test covers it.
- Issue 13 (cap long item text) now acts on one copy, so its gain is about half of what it was; issue 14 is unchanged.

Spent in batch2 so far: $0.33 of $1.00, two of two iterations.

## 2026-11-10: the lines of a text area kept apart for a run with the moves (not measured offline)

Follow-up to the supervised runs. The clicks land on the middle of an item, and `merge_blocks` had read the three
close lines of the document in front as one block, so "the line X" could not be aimed at. A run offered the moves
now keeps the lines of the focused text area or editor one item each (`perceive(..., apart=True)`); every other run
reads the blocks it always did, so no request of a run without the moves changes. The saved cases hold their items
as they were, so no offline pass can show the effect: it needs a supervised run of a goal that names a line. A word
inside a line is still not an item. Unit tests cover the split and that the flag follows the gate.

Supervised, on this code (runs `20261110-191418` and `-191556`, each command approved):

- A goal of select all, copy, open the find bar, paste there ran through in order, six steps, judged achieved: the
  follow-up picked `select_all`, `copy`, `find`, `paste` in turn (1.00, 1.00, 1.00, 0.97), where before it picked
  `select_all` six times. The field's `selected_text` was read from TextEdit's accessibility tree on the screens
  after each selection (the whole text after select all; the stale search term in the find field before the
  paste), so the first hardware read of it works on a Mac. The find bar showed one match for the pasted text.
- A goal naming the third line of the document, with the focus in the find bar at the start: the first two steps
  stopped at 0.36 and then triple-clicked the find field (the focus was not in the text area, so the lines were
  still one block, as designed), the third pressed Escape, and the fourth, with the text area focused and its three
  lines now items of their own, picked the named line at 0.93 and triple-clicked it. Only that line was selected.
- The writer's reviews took 65 to 77 s each in these runs (`openai/gpt-6-luna`, reasoning `none`), against 8 to 25 s
  of the classifier's whole work in the run. If speed is the next goal, the writer's latency is the largest piece.

## 2026-11-10: the moves gate on OSWorld's tasks, and a wider shortcut catalog (no iteration; $0.01)

Cluster: the one OSWorld task this agent has ever failed in `benchmarks/osworld/` (of 7 distinct tasks, all in the
Chrome domain) is "bring back the last tab I shut down", which is one chord (reopen the closed tab) that the catalog of
fifteen did not hold. The gate (`needs_moves`) was run over the instructions of all 369 OSWorld 1.0 tasks, text only
(public task text, $0.006): that task scores 0.78 and opens it.

- The gate opens for 195 of the 369 (53%) at `MOVES_NOUL` 0.5: 80 of 101 multi_apps tasks, 30 of 47 Impress, 27 of 47
  Calc, 16 of 23 Writer, 5 of 46 Chrome. Scores centre on 0.52 (quartiles 0.34, 0.52, 0.66), against 0.05 to 0.36 for
  the plain goals of the earlier probe, so on these productivity goals the gate is close to a coin flip.
- Only 27 instructions name a move in so many words (copy, paste, undo, drag, right click, bold...; a lower bound,
  since a goal rarely says which move it needs); 22 of the 27 open the gate. 173 of the 195 that open name none:
  align a text box, fill a column with a formula, add folders to a workspace. A run the gate opens for pays about
  3.4 points of silver agreement and 7% of request bytes (iteration 3 above), so on this benchmark the gate would
  charge half the tasks for a move that perhaps a tenth need. A threshold trades one for the other: 0.6 opens 36%
  and keeps 17 of the 27, 0.7 opens 19% and keeps 15. There is no ground truth here to choose by, and a missed
  move costs more than a needless one, so 0.5 stays; the way to choose is a run of a task set with the gate forced
  open, shut and automatic, which takes a cloud VM and the maintainer's approval.
- The shortcut catalog grows from fifteen to twenty-five: reopen the closed tab, address bar, bookmark, new window, open a
  file, save as, print, bold, italic, underline. They sit in the shortcut question only, a request of its own, so
  the kind question and the measured numbers above are untouched. Asked of Jev with a goal written for each of the
  fourteen entries tried (three repeats, the new and the old alike): 42 of 42 picks right, the OSWorld task's goal
  at 1.00 for `reopen_tab`.

Also in the catalog, to a total of thirty-three: the keys that only move the focus or the cursor, so as safe as a scroll:
Tab and Shift-Tab (the next and previous field, form control or spreadsheet cell), the four arrows, Page Up and Page
Down. The agent had Return and Escape and no other key, so filling a form or a sheet cell by cell, or walking a list,
meant a click on every item. Asked again of Jev with the whole catalog and a goal for twenty of its entries, three
repeats each: 60 of 60 right (`bold` and `arrow_left` the least sure, 0.65 to 0.86). The key tables of the Mac and Windows
adapters and the OSWorld mapping each got the new keys, with a test that every catalog key has a key code on both.
Not run on hardware: a run that fills a form with Tab.

Issues 13 and 14, sized after the pointers (bytes only, no model call, 827 saved requests, now 17.2 KB a request): capping
each item's text in the state at 120 characters saves 165 bytes a request (1.0%), at 80 characters 311 bytes (1.8%), since the long items are few and the pointers
already removed their second copy. Not worth the risk of cutting the phrase a goal names: issue 13 is not done. The site and
browser questions are 1.1 KB of 17.2 KB now (6.6%, up from 2.4% before the pointers), about 3% of the input tokens;
moving them to a follow-up for the 14% of steps that open a site would save that on the rest and add a round trip
(0.8 s a decide) to the 14%. A pass would settle whether the picks hold; it needs a batch iteration, so it waits.

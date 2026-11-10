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

## 2026-11-10: iteration 2 of batch1, a stall that no rule counted (PR 24, kept)

A supervised run on a goal the browser's account blocked opened the same URL four times before it was
stopped by hand. The repeat rule counts actions already taken on the same screen, and an error page reads a
line differently each capture, so every open looked like a first. `runner.repeating` now counts navigations
(`use_browser`, `open_app`) whose history line equals the one before, and ends the run as `stalled` on the
third. Scenario `l32c` fails before and passes after. Against the 118 acting runs on disk, 5 hold three or more
identical navigations in a row and none was judged achieved, so no run that worked would have been cut. The
request to the decision model is unchanged, so there is no pass for it.

## 2026-11-10: iteration 3 of batch1, moves beyond clicking and typing (kept behind a gate)

Not a failure cluster but a capability gap: the agent could not copy, paste, find, switch tabs, open a context
menu, double-click, select text, or drag (issues 7 to 10). Built as new kinds of action, each in its own
commit: `press_shortcut` (a 15-entry catalog, its own follow-up question), `right_click_item`,
`double_click_item`, `select_item_text` (all reuse the item answer, no new request) and `drag_item` (a
`target` follow-up question).

- Ungated, one kind alone cost agreement. `press_shortcut` in every step's kind question: silver agreement
  0.601 to 0.575 over six repeats against the same six on the unchanged code (sd 0.014 and 0.010 across
  repeats). It picked a shortcut in 12 of 642 asks, 10 of them `none`; the loss was elsewhere: 12 asks moved
  from `scroll_down` to a click and 10 to `press_escape`. Offered to every step, the clicks and the drag
  grow the kind question by 72% and the request by 7.0%, and agreement fell to 0.564 over three repeats
  (0.598 on the unchanged code), with the new kinds picked 6 times, all `select_item_text`.
- The loss is concentrated: three cases went from mostly right to mostly wrong, two of them in one run from
  2026-10-29. Restricted to cases from 2026-11-01 on (21 cases) the drop was larger (0.476 to 0.405), but that
  is too few cases to say more than "not a rounding error".
- So the moves are offered to a run only when its goal needs them. Before the first step the decision model is
  asked once, of the goal alone, whether it needs a move that clicking and typing cannot make (a Noul, as the
  read-only question). On 20 hand-written goals that need one it answered 0.58 to 0.98, on 16 that do not 0.05
  to 0.36; on the 69 distinct goals in the saved runs 13 reach 0.5, the threshold (`MOVES_NOUL`), so about 19% of
  real runs would see the moves. The probe cost $0.0017.
- With the gate closed, every request is byte-identical: `clicker-eval size` reads +0.0% in every part and all
  642 requests of a six-repeat pass are cache hits, so the unchanged agreement numbers are not re-measured but
  reproduced from the cache. The answer model's instructions follow the gate, so it never sends the
  classifier to a move it was not offered (scenarios `l75` to `l77`).
- Row: `20261110T220134Z.jsonl` (all four moves offered, 3 repeats).

Verdict: kept, behind the gate. Open: agreement for the 19% of runs that open the gate is 0.564 on these saved
steps against 0.598, and those steps are ones that mostly needed no move, so it is a ceiling on harm and not a
measure of benefit. What they gain is not measurable offline, because the saved screens do not react. It
needs supervised runs, and the Quartz right-button, click-state and drag paths have not run on hardware.


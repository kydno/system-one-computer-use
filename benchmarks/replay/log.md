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

Nothing else logged yet.

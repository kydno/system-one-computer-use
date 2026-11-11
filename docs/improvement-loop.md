# Improvement loop

How to tell whether a change to the loop helped, from the runs already on disk, without touching
the machine. `clicker-eval` is the tool; this page is the procedure an agent or a person follows
with it. Rules for agents are in [AGENTS.md](../AGENTS.md).

## What it measures

| Tier | Answers | Cost | Command |
|---|---|---|---|
| 0. Free checks | Do the tests pass? How many bytes does each saved step's request cost now? | $0 | `uv run pytest`, `clicker-eval size` |
| 1. Decision cases | On a saved screen, does the decision model pick the right action, how sure is it, and for how many tokens? | cents a pass | `clicker-eval decisions` |
| 2. Supervised runs | Does the fix work in the real app? | the maintainer's attention | `clicker "<goal>" --act`, or the menu bar |

Tiers 0 and 1 never touch the machine's screen, input, or apps. Only tier 2 shows that a change
works for real, so a batch of changes ends with it. Offline numbers are evidence, not that proof.

## How a case is made

`harvest` reads each run folder under `runs/` and freezes every saved step into a case under
`.private/evals/cases/`: the state and the criteria the classifier was sent (from
`step-NNN-payload.txt`), what it answered (`step-NNN-answers.json`), and how the run ended
(`run.json`). A case is rebuilt with the loop's own `decide.base_state` and `build_questions`, so a
change to how the request is built shows in the number. `check` says how many cases the current code
rebuilds exactly as they were sent; wording that changed in `decide.py` since a run shows up there,
not as an error.

A case's expected action is one of:

- **gold**: set with `clicker-eval label`, by a person or by an agent that read the case with
  `show` and the run's own `step-NNN.png`;
- **silver**: the pick a run made when the answer model judged that run achieved. The answer model
  can be wrong, so silver is a regression guard, not the truth;
- none: the case is not scored.

The classifier does not pick the same item every time, so a pass can repeat each case
(`--repeats 3`). A change counts only when it moves a number by more than the noise between repeats.
Replies are cached by request, so a change that leaves a request alone leaves its answer alone and
a pass pays only for what changed.

## Budgeted batches

A command that asks a model needs an open batch: a dollar cap and a number of iterations that the
maintainer approved.

```
clicker-eval batch open --cap 4 --iterations 3
clicker-eval decisions --plan          # requests a pass would send, how many are cached
clicker-eval decisions --repeats 3
clicker-eval batch iteration --note "what this iteration tries"
clicker-eval batch status
clicker-eval batch close
```

Every request is charged to `.private/evals/ledger.jsonl` from the cost its reply reports (or an
estimate when it reports none), and the command refuses before a request that could pass the cap.
A pass that runs out of budget stops, keeps what it has, and says so.

## One iteration

1. `clicker-eval digest --since <the run folder name at the last change to the loop>`: take the largest cluster
   of failures. A failure from before a fix is no failure of the code as it is now, and a stop on a goal too
   vague for any classifier ("yes", "check it urself") is the loop handing off as designed; look for a
   cluster with a screen a person could act on.
2. `clicker-eval show <run>/<step>` for up to ten of its failure points, and `label` each with the
   right action.
3. Reproduce it: the gold cases that fail, plus a scenario in `tests/test_scenarios.py` when it is
   a loop or stop-rule problem.
4. Change the loop, never the case. The ground rules hold:
   the action set stays mutually exclusive, code decides facts, free text comes only from the
   writer.
5. Gates, cheapest first: ruff and pytest; `clicker-eval size` (bytes by part against the
   baseline); the target gold cases; a full `decisions` pass.
6. Keep the change only if its gold cases flip in at least two of three repeats, silver agreement
   does not fall by more than the noise, and request bytes do not rise by more than 2% without a
   stated reason. Otherwise revert, and log why.
7. A kept change becomes one pull request for the maintainer to merge, with the numbers before and
   after.
8. `clicker-eval report --record <pass file>` appends the pass to `benchmarks/replay/`, and
   `benchmarks/replay/log.md` gets an entry whether the change was kept or not.

## Privacy

Cases hold the goals and screen text of real runs, and the repository is public. They stay in
`.private/evals/` (ignored by git). The rows in `benchmarks/replay/` hold numbers and model ids
only. No goal, screen or item text, or screenshot from a case goes into a commit, pull request, issue, or
log; a pull request names a run by its folder and step, never by what was on its screen.

## Limits

- Silver labels rest on the agent's own verdict, which can be a false "done"; the maintainer's
  verdicts on supervised runs replace them over time.
- The answer model on the free tier routes to a different model per call and is rate-limited, so its
  numbers are sampled and advisory, never a gate.
- Offline cannot show that a new ability works, because the saved screens do not react. That needs
  a tier that does.

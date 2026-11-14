# Run folder

Every run writes `runs/<timestamp>/` so a stall can be replayed and fixed offline:

| file | contents |
|---|---|
| `run.log`, `run.json` | everything printed; goal, outcome (`done`, `nothing helps`, `low confidence`, `stalled`, `stuck`, `step limit`, `dry run`, `aborted`, `crashed`), `answer` and `goal_achieved`, seconds, `calls` (requests, share and seconds per model), `usage` (requests, uncached input, cached input, and output tokens, and `cost` in USD per model id), `usage_by_role` (the same under the role that asked: `decision`, `reviewer` for the answer model's reviews, `writer` for fills and URL proposals; the menu bar's usage breakdown reads it), `cost` (the run's total, from the replies that report one, as OpenRouter's do, a decision reply that refused a question included; null when none did), `ended_at`, `handoffs` (step, why the classifier stopped, the focus given or the scroll the writer took, and what the writer said then), `handoff` (`handoff.json` when the run wrote one, else null), `questions` and replies, `earlier_tasks` (the goals given before this one, from `--earlier-tasks`), every action, config, and `timing` (mean and max seconds per phase, with `steps_timed`) |
| `handoff.json`, `handoff-raw.png` | only when a run stopped (any outcome in the list above but `dry run`, `aborted` and `crashed`) with the goal not achieved: the story an outer agent (Claude, or another computer-use model) needs to go on from the screen the run ended on rather than from the goal alone. `goal`; `outcome` and `why` (the outcome in the words the writer is given); `answer`, the writer's last; `last_focus`, the focus that last answer offered, which a final stop never takes, so it is often the next thing to try (null when it offered none); `actions`, in order, each with the `app` and `url` it was taken on and `then`, the app and URL of the screen it led to (the one the next action was taken on, or the one the run ended on) and whether that screen differed from the one before (`changed_screen`), null when nothing read the screen after it; `handoffs` and `questions`, as in `run.json`; `earlier_screens`, the text of the distinct screens passed before the last, oldest first, within the 600 lines the writer gets; `current_screen`, its `app`, `url`, focused `field` and `text` in reading order, and `raw`, the file holding its capture (`handoff-raw.png`; null with the rest when an action ran and nothing read the screen after it); `moves`, the actions the classifier was offered, so the outer agent knows what the loop could not do; `read_only`. The same object goes out as a `handoff` event on `--events`, with its path as `file`, before `end`. It holds screen text, so it stays in the run folder like the captures. The run types no credential, so none is in `actions`, and the user's email is never in it. `clicker-takeover` reads it (see [takeover](takeover.md)). |
| `takeover.json`, `takeover.log`, `takeover-step-NNN.png` | only after `clicker-takeover` took the run over from `handoff.json`: what the takeover model did, its verdict, and what it cost; see [takeover](takeover.md) |
| `step-NNN-review.json` | what the writer made of a stop on that step: each answer, focus or question, your reply, and whether the run was handed back |
| `answer-raw.png` | the capture the answer was read from, when an action made the last step's capture stale |
| `step-NNN-raw.png` | the capture |
| `step-NNN.png` | items numbered in blue, accessibility ones orange, the chosen one red, the focused field green |
| `step-NNN-payload.txt` | the exact `state` and criteria sent to the decision model, then every item with source, role, box, click point, confidence, then the off-screen controls |
| `step-NNN-answers.json` | every probability the classifier returned, the off-screen controls it was offered, the actions already tried on that screen, the idle and repeat counts the stop rules stood at, plus `timing` for that step |

Each step also logs what it cost, so a slow phase is obvious:

```
  timing: capture 0.31s  screenshot 0.28s  app 0.01s  window 0.02s  field 0.01s  url 0.01s  ocr 0.31s (22% of screen)  ax 0.06s  decide 0.21s  act 0.05s  total 0.95s
```

`capture` covers the four round trips under it; `act` is left out when the step did not act.

Replay a saved capture as if it were live, without touching the screen:

```
uv run clicker "same goal" --image runs/<ts>/step-003-raw.png --app "Google Chrome" --url "https://example.com/"
```

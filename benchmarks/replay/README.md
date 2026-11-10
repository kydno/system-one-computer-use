# Offline replay record

Each `<stamp>.jsonl` here holds rows written by `clicker-eval report --record`: one row per pass,
with numbers, the model ids that answered, the commit, and whether the working copy differed from
it. A row holds no goal, no screen text, and no case id, so it can be committed. Rows are never
edited; a new pass is a new row. See [docs/improvement-loop.md](../../docs/improvement-loop.md).

- `config.json` fixes the models a pass runs on, so that two passes compare. Change it in its own
  commit, and say why in `log.md`.
- `log.md` has one entry per improvement iteration, kept or not, so a change that did not help is
  not tried again.

The cases the rows were scored on live in `.private/evals/` on the maintainer's machine and are
never committed: they are frozen from real runs.

# Decision models

Every decision goes to a decision model: a model that answers named questions about a state
with a label and a probability for each label, not with text. The agent asks one such request per step
(see [how a step works](how-a-step-works.md)). Two services answer it with the same request and
the same reply, so the agent needs neither one in particular:

| service | URL | key | default model |
|---|---|---|---|
| OpenRouter's Decisions API | `https://openrouter.ai/api/alpha/decisions` | `OPENROUTER_API_KEY` | `~typesafe/jev-latest` |
| TypeSafe's own API | `https://api.typesafe.ai/v1/systemone` | `TYPESAFE_API_KEY` | `jev-latest` |

With one key set, that service answers. With both, OpenRouter does, unless
`CLICKER_DECISION_PROVIDER=typesafe`. Neither set stops `clicker` before it captures anything.

## Models on OpenRouter

`CLICKER_DECISION_MODEL` names any decision model OpenRouter serves. The agent is set up for these,
and the offline tests check its requests and replies with each id:

| model | notes |
|---|---|
| `~typesafe/jev-latest` | TypeSafe's Jev, whatever its newest version is; the default |
| `inception/mercury-decide` | Inception's decision model; up to 255 labels per question, as Jev |
| `openai/gpt-6-luna-decisions` | GPT-6 Luna through OpenAI's Decisions API; 1M tokens of context |

`typesafe/jev-router` is a chat model, not a decision model: it routes each chat request to a
model and an effort. It cannot answer a decision, but it can be the writer (see
[writer endpoints](writer-endpoints.md#openrouter)).

## When a model does not answer

Every answer is checked against its question before the loop reads it: it must be there, be of the
question's kind, and name a label the question offered. A model that refuses a question, skips it,
or names something else gives no decision for that step, and so does a service that cannot be
reached after two retries. The run never guesses from it: the step hands the run to the writer, as
any stop does, which reads the screen, answers, and may send the classifier back with a focus. A
failed check of typed text keeps the text and says it was not verified.

OpenRouter answers a Luna request that Luna refuses any part of with a 502 for the whole request,
so on Luna a refusal reaches the agent as an error rather than as one refused answer; the effect is
the same.

## Variables

| variable | purpose |
|---|---|
| `OPENROUTER_API_KEY` | decisions on OpenRouter; also the writer, unless another writer endpoint is named |
| `TYPESAFE_API_KEY` | decisions on TypeSafe |
| `CLICKER_DECISION_PROVIDER` | `openrouter` or `typesafe`, when both keys are set |
| `CLICKER_DECISION_MODEL` | the model id; the defaults are in the first table |
| `TYPESAFE_BASE_URL`, `TYPESAFE_DEFAULT_MODEL` | read as TypeSafe's SDK reads them, for TypeSafe only |

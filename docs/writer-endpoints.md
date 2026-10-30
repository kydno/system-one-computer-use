# Writer endpoints

The writer types text, proposes URLs, and reads the screen whenever the classifier stops. By
default it is Claude on `api.anthropic.com`, or on OpenRouter when `OPENROUTER_API_KEY` is set
and no other endpoint is named. These variables change the model or send it to another endpoint.

| variable | required | purpose |
|---|---|---|
| `CLICKER_WRITER_BASE_URL` | no | send the writer to another endpoint; unset means `api.anthropic.com` |
| `CLICKER_WRITER_API_KEY` | no | the key for `CLICKER_WRITER_BASE_URL`, if it checks one |
| `CLICKER_WRITER_API` | no | what that endpoint speaks: `anthropic` (the default) or `openai` |
| `CLICKER_WRITER_MODEL` | no | types text and proposes URLs; defaults to `claude-haiku-4-5`, on OpenRouter `inception/mercury-3` at medium effort |
| `CLICKER_ANSWER_MODEL` | no | reads the screen whenever the classifier stops; defaults to `claude-sonnet-5`, on OpenRouter `openai/gpt-6.1-terra` |
| `CLICKER_WRITER_VISION` | no | `false` for an answer model that reads text only; defaults to `true` |
| `CLICKER_WRITER_REASONING` | no | the reasoning effort the writer's calls ask an OpenAI-API model for, such as `none`; unset leaves it to the model, except `medium` for OpenRouter's default writer. A call with an effort gets tokens to think with on top of its own limit (1024 at `low`, 2048 at `medium`, 4096 at `high`). Thinking can still run past that on some calls and cut the reply off; a reply cut off at its limit is asked for once more with twice the room |
| `CLICKER_ANSWER_REASONING` | no | the same for the answer model; unset leaves it to the model, except `low` for OpenRouter's default answer model |
| `CLICKER_ANSWER_SORT` | no | the order OpenRouter tries the answer model's providers in: `price` for the cheapest first, `throughput` for the fastest; unset leaves it to OpenRouter, which weighs price and uptime. Either way it falls back to the next provider when one fails. The menu bar app's settings set this and `CLICKER_ANSWER_MODEL` |
| `CLICKER_WRITER_PROVIDER` | no | the one OpenRouter provider the writer's calls go to, by its slug or tag such as `deepinfra/fp8`, with no fallback, so a busy provider fails the call; unset leaves routing to OpenRouter |

## OpenRouter

With `OPENROUTER_API_KEY` set, and neither `CLICKER_WRITER_BASE_URL` nor `ANTHROPIC_BASE_URL`, the
writer goes to `https://openrouter.ai/api/v1` over OpenAI's Chat Completions API, with that key and
no other. Any chat model OpenRouter serves can write or answer, by its OpenRouter id:
`typesafe/jev-router` picks a model and effort per request, and other vendors' models work as
well as Claude. The answer model reads a screenshot, so pick one
that sees images or set `CLICKER_WRITER_VISION=false`. `CLICKER_WRITER_API=anthropic` keeps the
writer on Anthropic's own API even with the OpenRouter key set.

```
OPENROUTER_API_KEY=sk-or-...
CLICKER_WRITER_MODEL=typesafe/jev-router
CLICKER_ANSWER_MODEL=anthropic/claude-sonnet-5
```

## Other models

Point `CLICKER_WRITER_BASE_URL` at any endpoint that speaks the Anthropic
Messages API or, with `CLICKER_WRITER_API=openai`, OpenAI's Chat Completions API: LM Studio,
Ollama, vLLM, a LiteLLM proxy, DeepSeek. Name the models it serves. The full request URL works as
well as the root; for the OpenAI API keep the `/v1`. Such an endpoint may ignore structured-output
parameters, so the schema is also spelled out in the prompt, and code fences or a sentence around
the JSON are tolerated. On the OpenAI API a `json_schema` response format is asked for first, then
`json_object`, then none, stepping down only when the endpoint refuses one. Thinking is turned off,
since a model that thinks by default spends the writer's small token budgets on it and returns no
text. The answer model reads a screenshot; for a model that reads text only, set
`CLICKER_WRITER_VISION=false` and it gets the screen's text alone. A reply that cannot be read
refuses the step it was for, and the run goes on.

Keys never cross over: `CLICKER_WRITER_API_KEY` goes only to `CLICKER_WRITER_BASE_URL`, and
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY` and `OPENROUTER_API_KEY` never go there. On the Anthropic API it is sent in both
the `x-api-key` and `Authorization` headers, since proxies differ. Leave it empty for an endpoint
that checks no key.

## Examples

```
# LM Studio, either of its two APIs
CLICKER_WRITER_BASE_URL=http://localhost:1234
CLICKER_WRITER_MODEL=qwen3.8-flash-next
CLICKER_ANSWER_MODEL=qwen3.8-flash-next

# any OpenAI-compatible server
CLICKER_WRITER_API=openai
CLICKER_WRITER_BASE_URL=https://api.deepseek.com/v1
CLICKER_WRITER_API_KEY=sk-...
CLICKER_WRITER_MODEL=deepseek-v4.1-flash
CLICKER_ANSWER_MODEL=deepseek-v4.1-flash
CLICKER_WRITER_VISION=false
```

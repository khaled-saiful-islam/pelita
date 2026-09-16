# 001 — Provider adapter

## What it does

Routes every model call in Pelita through one adapter that speaks the OpenAI
chat-completions wire format. Switching from OpenAI to Groq, Ollama, OpenRouter,
vLLM or ILMU means editing three lines of `.env` and restarting. No code change,
no vendor SDK, no conditional branches scattered through the codebase.

## How it works

`app/providers/base.py` defines the protocol and the value types that cross it:

```python
class LLMProvider(Protocol):
    info: ProviderInfo
    def stream_chat(self, req: ChatRequest) -> AsyncIterator[StreamEvent]: ...
    async def complete(self, req: ChatRequest) -> Completion: ...
```

`stream_chat` yields `TokenEvent`, then exactly one `UsageEvent`, then one
`FinishEvent`. `complete` is used where streaming would be pointless — titles and
follow-up suggestions.

`app/providers/openai_compatible.py` is the implementation. It POSTs to
`{LLM_BASE_URL}/chat/completions` with raw `httpx` and parses the SSE response by
hand. That is deliberate: the moment a vendor SDK appears, "works against any
compatible endpoint" becomes a claim you have to keep re-verifying instead of a
property of the code. Nothing in the repository imports `openai`, `anthropic` or
any other vendor package.

`app/providers/registry.py` is the only module that names a concrete provider.

### Two behaviours worth knowing about

**Usage is labelled, never assumed.** Providers disagree about whether a
streaming response carries a usage block. When one is present it is used and
marked `UsageSource.PROVIDER`. When it is absent, tokens are counted with
`tiktoken` and marked `UsageSource.ESTIMATED`. Feature 013 surfaces that
distinction in the UI. A cost table that silently mixes measured and guessed
numbers cannot be trusted, so the difference is carried all the way through
rather than smoothed over.

**`stream_options` degrades on its own.** Pelita asks for
`stream_options: {include_usage: true}` because it produces exact counts. Some
providers reject the field with a 400. The adapter detects that specific
rejection, retries once without it, and stops sending it for the rest of the
process — falling back to estimated usage. The user sees a normal response.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `LLM_BASE_URL` | `https://api.openai.com/v1` | Base URL including `/v1`. Trailing slashes are stripped |
| `LLM_API_KEY` | *(empty)* | Sent as `Authorization: Bearer`. Omitted entirely when blank, which is what local Ollama wants |
| `LLM_MODEL` | `gpt-4o-mini` | Model identifier as the provider spells it |
| `LLM_TIMEOUT_SECONDS` | `120` | Per-request timeout |
| `LLM_MAX_TOKENS` | `2048` | Cap on the response |
| `LLM_TEMPERATURE` | `0.7` | Sampling temperature |

Verified provider settings:

| Provider | `LLM_BASE_URL` | `LLM_MODEL` |
|---|---|---|
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| Groq | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` |
| Ollama | `http://localhost:11434/v1` | `llama3.2` |
| OpenRouter | `https://openrouter.ai/api/v1` | `anthropic/claude-3.5-sonnet` |
| vLLM | `http://localhost:8000/v1` | the model you serve |
| ILMU | `https://api.ilmu.ai/v1` | `ilmu-v3.1` |

## How to extend it

To add a backend that is not OpenAI-compatible — a local transformers process, a
gRPC service, a queue — write one file implementing `LLMProvider` and add one
branch to `build_provider()`. Nothing else changes, because nothing else imports
a concrete provider. Feature 020 (demo mode) is exactly this: a second provider
that replays recordings, wired in with a single line.

## Known limits

- **Chat completions only.** No embeddings, images or audio. Those belong in
  their own protocols rather than bolted onto this one.
- **No tool/function calling.** Providers disagree too much about the dialect for
  a single adapter to abstract it honestly. Pelita gets tool results into the
  prompt through context contributors (feature 002) instead, which works
  identically everywhere.
- **`tiktoken` is an OpenAI tokeniser.** Estimates for Llama or Qwen models are
  approximate. This is why estimates are labelled rather than presented as fact.
- **Retry on `stream_options` rejection is per-process.** A restarted container
  probes once more. The cost is one failed request per process lifetime.
- **No automatic retry on 5xx or rate limits.** The error surfaces to the user
  with a readable message. Adding backoff is a change to one method.

## Tests

`backend/tests/test_provider_openai_compatible.py` — 13 tests covering token
streaming, provider-reported usage, estimated-usage fallback, unparseable chunks,
auth header presence and absence, URL normalisation, the four HTTP error classes,
the `stream_options` retry path, non-streaming completion, and timeouts.

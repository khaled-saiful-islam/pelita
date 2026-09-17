# 009 — Token and cost accounting

## What it does

Counts tokens and prices every turn, per message and per conversation. Pricing
is configuration, so the numbers stay right when a provider changes its rates or
you point the template somewhere else entirely.

## How it works

### Provenance is carried, not smoothed over

Some providers report usage during streaming and some do not. Pelita asks for
`stream_options: {include_usage: true}`, uses the reported figures when they
arrive, and counts with `tiktoken` when they do not. Every message records which
happened, in `usage_source`:

| value | meaning |
|---|---|
| `provider` | The model reported these counts |
| `estimated` | We counted them ourselves |

The UI says which, and a conversation total containing any estimate is marked
approximate. This is the whole point of the feature. A cost table that silently
mixes measured and guessed numbers is worse than no cost table, because it looks
authoritative.

`tiktoken` is an OpenAI tokeniser, so estimates for Llama, Qwen or ILMU are
approximate — which is exactly why they are labelled rather than presented as
fact.

### Six decimal places

A 40-token reply on `gpt-4o-mini` costs about $0.000006. Rounded to the usual
two or four places, every short message reads as free. Costs are stored as
`NUMERIC(12,6)` and computed with `Decimal`, never floats — floating point
addition over thousands of messages drifts, and this is money.

### Cancelled and failed turns are still priced

Tokens consumed before a stop were still paid for. The accounting event is
emitted from the `finally` block, so it happens on every path: success,
cancellation, and provider failure.

### Totals read the stored rows

`summarise()` sums what was persisted rather than re-pricing from scratch, so a
conversation total stays consistent with the per-message figures even after
rates change in `.env`.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `LLM_PRICE_INPUT_PER_1M` | `0.15` | Input price per million tokens |
| `LLM_PRICE_OUTPUT_PER_1M` | `0.60` | Output price per million tokens |
| `LLM_PRICE_CURRENCY` | `USD` | Label only — no conversion is performed |

Defaults match `gpt-4o-mini`. **Set these to your provider's real rates**, or the
cost column is fiction. Setting both to `0` keeps token counting and shows cost
as zero, which is the right setting for a self-hosted model.

## Where it appears

- Per message, beside the hover actions: `82 in · 118 out · 0.000083 USD`
- Per conversation, in the header: `200 tokens · 0.000083 USD`
- On the wire, as a `usage` SSE event after the last token

## How to extend it

- **Per-user budgets**: the data is already per message with a `user_id` on the
  conversation. A `SUM` and a check in `ChatService.stream_turn` is the whole
  feature.
- **Per-model pricing**: `Pricing` is constructed from settings in one place.
  A dict keyed by model name replaces it without touching `price()`.
- **A usage dashboard**: `summarise()` works over any message list.

## Known limits

- **Prices are global, not per model.** Switching `LLM_MODEL` without updating
  the rates gives wrong costs silently.
- **No currency conversion.** `LLM_PRICE_CURRENCY` is a label.
- **`tiktoken` approximates non-OpenAI tokenisers**, sometimes by 10–20%.
- **Cached-token discounts are not modelled.** Providers that bill cached input
  at a lower rate will be over-counted.
- **Historic costs are not re-priced** when rates change, which is correct for
  accounting and surprising if you expected otherwise.

## Tests

`backend/tests/test_accounting_and_language.py` — rate arithmetic, a realistic
turn priced to six places, the necessity of six places, zero rates, provenance
reaching the event, settings parsing, total summing, and one estimated message
marking a whole conversation approximate.

`backend/tests/test_chat_service.py` — every turn reports usage, estimation when
the provider reports none, persistence onto the message, and a cancelled turn
still being priced.

## Verified

Against ILMU: `prompt_tokens: 86, completion_tokens: 196, source: "provider"` —
measured, not estimated, because ILMU does report usage while streaming.

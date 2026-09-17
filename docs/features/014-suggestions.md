# 014 — Follow-up suggestions

## What it does

Three short follow-up questions as clickable chips after an answer. Clicking one
sends it.

## How it works

One non-streaming call once the answer is complete, asking for a JSON array of
questions written from the user's point of view. The result arrives as a
`suggestions` SSE event after `usage` and before `done`.

Generating them after the answer rather than alongside it means they cost
nothing until the user already has what they asked for, and a failure costs
nothing at all.

### Only after a clean finish

Suggestions are skipped when `finish_reason` is anything but `stop`. Offering
follow-ups to a half-written answer wastes a call and reads as the app not
noticing it was stopped.

### Only on the latest answer

Chips render under the most recent message and clear the moment a new turn
starts. Chips under an old answer are stale by definition.

### Parsing is defensive

Models wrap JSON in prose and code fences however they like, so the array is
located inside the response rather than assumed to be the whole of it. An
array nested in an object — `{"suggestions": [...]}` — is recovered too, which
is the difference between working on most providers and working on the one it
was written against. Anything unparseable produces no chips.

Suggestions are deduplicated case-insensitively, truncated to 80 characters, and
capped at `SUGGESTIONS_COUNT`.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `SUGGESTIONS_ENABLED` | `true` | Set `false` for one fewer call per turn |
| `SUGGESTIONS_COUNT` | `3` | How many to ask for |

## How to extend it

- **Cheaper generation**: the call uses the same provider as chat. A second
  provider pointed at a smaller model is a constructor argument.
- **Persistence**: chips are per-turn and not stored. Add a `suggestions` JSONB
  column on `messages` to keep them across reloads.
- **Different chips**: the prompt in `suggestion_service.py` is the whole
  behaviour.

## Known limits

- **One extra model call per turn**, which is real money at volume.
- **Latency after the answer.** The chips appear a second or two late; the
  answer is already readable, so this is not blocking.
- **Not persisted.** Reloading a conversation shows no chips.
- **Quality follows the model.** Weaker models suggest near-duplicates;
  deduplication catches exact repeats, not paraphrases.
- **They lengthen conversations**, which is the point and also the risk.

## Tests

`backend/tests/test_memory_and_suggestions.py` — arrays found inside prose and
fences, arrays wrapped in objects recovered, unparseable output yielding
nothing, non-string entries dropped, case-insensitive deduplication, the count
cap, truncation and whitespace collapsing.

`backend/tests/test_chat_service.py` — suggestions emitted after a clean finish
and skipped after cancellation.

## Verified

"What is a monsoon?" produced three chips opening different directions: how they
form, whether they are dangerous, and where they happen.

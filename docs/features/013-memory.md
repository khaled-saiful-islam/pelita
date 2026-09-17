# 013 — Memory

## What it does

Remembers facts about you across conversations. Some you type in settings; some
Pelita extracts from what you say. All of them are listed, editable, switchable
and deletable in one place.

## How it works

### Two sources, kept distinguishable

Every memory records where it came from:

| `source` | meaning |
|---|---|
| `user` | Typed in settings |
| `extracted` | Proposed by the model after a turn |

The settings list labels them "Added by you" and "Added by Pelita". People trust
what they wrote themselves and want to audit what was inferred about them, so
collapsing the distinction would be the wrong simplification.

### Injection

`MemoryContributor` at order 200 renders enabled facts as one system message,
after the system prompt and before anything from the current turn — standing
facts should read as background, not as something just said.

Facts are trimmed to `MEMORY_TOKEN_BUDGET` whole facts at a time. If the budget
is too small for even one, the contributor returns nothing rather than a header
with an empty list under it.

Facts are passed *into* the contributor rather than fetched by it. A contributor
that opens a database session is a contributor that can fail a turn on a
connection pool exhaustion; `ChatService` loads them and hands them over.

Loading memories is wrapped so failure degrades the answer instead of breaking
the turn.

### Extraction

After a clean finish, the exchange goes to the model with an extraction prompt
asking for durable facts as a JSON array. Everything returned is stored with
`source='extracted'`, skipping duplicates and anything over the limit.

Extraction runs only on `finish_reason == stop`. Extracting from a cancelled or
failed answer would learn from something the user did not accept.

It never raises. Extraction is a nicety; the conversation it came from is not.

### Disabling versus deleting

Unchecking a memory keeps the row and excludes it from the prompt. "Stop using
this" should not have to mean "delete it" — the fact may be right but irrelevant
to what you are doing today.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `MEMORY_AUTO_EXTRACT` | `true` | Set `false` for one fewer model call per turn and no automatic facts |
| `MEMORY_MAX_PER_USER` | `100` | Hard cap; adding beyond it is refused with a readable message |
| `MEMORY_TOKEN_BUDGET` | `512` | Ceiling on what reaches the prompt |

## Endpoints

| method | path | purpose |
|---|---|---|
| `GET` | `/api/memories` | All memories, newest first, plus the limit |
| `POST` | `/api/memories` | Add one (`source='user'`) |
| `PATCH` | `/api/memories/{id}` | Edit content or toggle `enabled` |
| `DELETE` | `/api/memories/{id}` | Remove one |

## How to extend it

- **Semantic deduplication**: `MemoryService.add` compares lowercased strings.
  An embedding comparison would catch overlapping facts — see known limits.
- **Confirmation before storing**: have `extract` return proposals to the UI
  instead of calling `add`. The service already separates the two.
- **Scoped memory**: add a `scope` column and filter in `list_for`.
- **Ranking**: the contributor takes facts in the order given, so a relevance
  sort upstream needs no change here.

## Known limits

- **Deduplication is exact, not semantic.** "The user lives in Kuala Lumpur" and
  "The user is a backend engineer in Kuala Lumpur" both persist. Observed in
  practice: typing one fact and letting extraction run produced two overlapping
  rows.
- **Extraction costs a model call per turn.** `MEMORY_AUTO_EXTRACT=false`
  removes it.
- **Extraction quality follows the model.** A weaker model stores transient
  detail. Everything it stores is visible and deletable, which is the mitigation.
- **No review step.** Extracted facts go straight in. They are labelled and
  removable, but they are not confirmed first.
- **Memory is global to a user**, not per conversation or per project.
- **Facts enter the prompt in reverse chronological order**, not by relevance,
  so the budget favours recent over useful.

## Tests

`backend/tests/test_memory_and_suggestions.py` — storage and listing,
whitespace normalisation, empty and overlong rejection, case-insensitive
duplicate rejection, the per-user limit, invalid sources, editing, disabling
keeping the row while leaving the prompt, deletion, another user's memory
returning not-found, and extraction failure returning nothing rather than
raising. Plus the contributor's rendering, budget trimming, too-small-budget
case and order.

`backend/tests/test_chat_service.py` — enabled memories reach the prompt,
disabled ones do not.

## Verified

A typed memory ("backend engineer in Kuala Lumpur") was used to answer "Where do
I live and what do I do?", and extraction added two labelled facts from the same
exchange.

# 010 — Language auto-detection

## What it does

Detects the language of the first message and replies in it. Verified for Bahasa
Melayu, English, Tamil, Chinese and Bengali.

## How it works

`lingua` classifies the first user message. The result is stored on the
conversation, and `SystemPromptContributor` appends an instruction:

> The user is writing in Bahasa Melayu. Reply in Bahasa Melayu unless they ask
> for another language.

### Why a library and not the model

An LLM classification call would cost tokens on every new conversation, add
latency before the first token, and be untestable without a network. Detection
here is deterministic, free, instant, and asserted in unit tests against all five
required languages.

### Detected once, not per turn

Re-detecting every message would flip the reply language the moment someone
typed "ok" — which is not reliably any language. Detection runs when
`conversation.language` is null, and the answer sticks. Starting a new
conversation is how you change it.

### Short text falls back rather than guessing

Below 12 characters, or below 55% confidence, the configured default is used.
"hi" is valid in several languages and "hai" is Malay; guessing from two
characters is worse than a sensible default.

### The language list is deliberately short

`lingua` loads a model per language. Restricting to five keeps memory small and
markedly improves accuracy on short text — and a first message is usually short.
Adding languages is one `.env` value, at some cost to both.

Unknown codes are logged and skipped rather than fatal. Fewer than two usable
languages disables detection, because there is nothing to choose between.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `SUPPORTED_LANGUAGES` | `en,ms,ta,zh,bn` | ISO 639-1 codes to choose between |
| `DEFAULT_LANGUAGE` | `en` | Used for short or low-confidence text |

`LANGUAGE_NAMES` in `language_service.py` maps codes to the names used in the
prompt; it already covers seventeen languages.

## How to extend it

- **More languages**: add codes to `SUPPORTED_LANGUAGES`. Add a display name to
  `LANGUAGE_NAMES` if it is not one of the seventeen already listed.
- **Per-user preference**: skip detection when the user has set one; the
  contributor reads `ctx.language` and does not care where it came from.
- **Per-message detection**: remove the null check in `_begin_turn`. Read the
  reason above first.

## Known limits

- **First message only.** A conversation that switches language mid-way keeps
  the original instruction.
- **It is an instruction, not a guarantee.** A model that ignores it will reply
  in whatever it likes; Pelita does not verify the response language.
- **Code-switching confuses it.** Mixed Malay and English — normal in Malaysia —
  resolves to whichever dominates.
- **Romanised Malay and Indonesian are close.** With `id` in the list, short
  Malay text can be misread.
- **Detection cannot be overridden from the UI.** There is no language picker.

## Tests

`backend/tests/test_accounting_and_language.py` — all five required languages
detected from real sentences, short text falling back, the default honoured,
unsupported languages staying inside the configured set, unknown codes ignored
rather than fatal, a single-language list disabling detection, and the prompt
instruction naming the language.

`backend/tests/test_chat_service.py` — the language is detected, stored, reaches
the system prompt, and is not re-detected on later turns.

## Verified

A Malay question produced `language: "ms"` and a Malay answer end to end through
the browser.

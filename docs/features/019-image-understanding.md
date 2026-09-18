# 019 — Reading uploaded images

## What it does

Attach a photo, screenshot or scan and ask about it. It counts as one of the
three files a chat may hold, and once read it works exactly like any other
attachment — including alongside them.

```
You:  [receipt.png]  What was the total, and which item cost the most?
Bot:  Based on the receipt.png file:
      • The total was RM 59.36.
      • The item that cost the most was Nasi Lemak Ayam.
```

Off by default. Set `VISION_MODEL` and the file picker starts accepting images;
leave it empty and they are refused with a message saying why.

## How it works

### The image is read once, at upload, into text

That one sentence is the design. `DocumentService` sends the image to a vision
model, stores the transcript in the same `text` column every other attachment
uses, and from that point nothing downstream knows an image was involved:
excerpt selection, the token budget, the contributor at order 350, the card in
the transcript, the three-file limit and the search suppression all work
unchanged.

The alternative — keeping the bytes and sending them to the chat model on every
turn — means multimodal message parts, which means `ChatMessage.content` stops
being a `str`. That change reaches every contributor, the token counter and the
history builder, to serve one feature. Reading once is a fraction of the code
and a fraction of the cost.

What it buys, and what it costs:

| | |
|---|---|
| ✅ | A read image costs no more per turn than a text file |
| ✅ | Works with the existing budget, cards, limits and cross-file questions |
| ✅ | A model that cannot see still runs the whole app |
| ❌ | The transcript is fixed at upload. "Look again at the top-left corner" re-reads text, not pixels |

The second row of ❌ is why the prompt matters more than usual.

### Transcribe, don't describe

`vision/base.py` holds one prompt, and it asks for a transcription: tables as
rows with their headers and every cell, labels attached to their numbers, all
figures, units and dates exactly as shown — then one final `Depicts:` line
describing the picture.

A model asked to *describe* a receipt writes "a receipt from a restaurant". The
figures, which are the only reason anyone uploaded it, never reach the
conversation. The `Depicts:` line is appended rather than substituted so a
photo with no text in it still contributes something.

It is deliberately question-agnostic, because the image is read before the
question is asked and the same transcript has to serve every later turn.
`temperature` is `0.0`: a creative reading of an invoice is a wrong reading of
an invoice.

### Preparation, before anything looks at it

`services/image_prep.py` does three things, in one place, so the transcript and
the thumbnail cannot disagree about which pixels they describe:

1. **Rotation is applied**, not left in EXIF. A model reads pixels, not tags — a
   photo taken sideways is transcribed sideways, and the answer is confidently
   wrong about a page it never saw upright.
2. **Downscaled** to `VISION_MAX_PIXELS` (2.5 MP). A phone photo is 12 MP; a
   vision model bills for tiles it gains nothing from, and past about 2.5 MP
   more pixels stop producing more text.
3. **Flattened onto white** if there is an alpha channel, because JPEG has none
   and dropping it turns transparent regions black — hiding any dark text on
   them.

### A card that shows the picture

The original bytes are not stored, so a small JPEG data URI goes on the document
row and the card renders it. A card for a photo that shows a generic document
icon reads as a failed upload, and there would be nothing else to show.

The thumbnail is built from the *original* bytes rather than the downscaled
copy: that copy is sized for a model, and its compression would show.

### It is a provider, not a special case

`vision/` mirrors `providers/`: a `ImageReader` protocol (`base.py`), an
OpenAI-compatible implementation (`openai_compatible.py`), and a registry
(`registry.py`) that returns `None` when no model is configured — exactly as
`build_tools()` returns nothing without a search key.

`None` is what makes an image an *unsupported file type* rather than a broken
one. It is refused at the picker, refused at `classify()`, and the message names
the real reason: *"photo.png is an image, and no vision model is configured."*
"Not a supported file type" would send someone looking for a converter when the
fix is one config line.

## Configuration

**The size and count limits are the document limits.** There is no separate
image budget: an image is bound by `DOCUMENT_MAX_BYTES` (5 MB) like any other
file, and counts as one of the `DOCUMENT_MAX_PER_CONVERSATION` (3) a chat may
hold. Two text files and one photo is a full chat. One set of limits is one set
of error messages, and the user never has to learn which kind of file they are
near the limit of.

| variable | default | what it does |
|---|---|---|
| `VISION_MODEL` | *(empty)* | The vision model. **Empty disables images entirely.** |
| `VISION_BASE_URL` | *(falls back to `LLM_BASE_URL`)* | Only needed when vision lives elsewhere |
| `VISION_API_KEY` | *(falls back to `LLM_API_KEY`)* | Same |
| `VISION_MAX_PIXELS` | `2500000` | Downscale target before sending |

Known-working values:

| provider | `VISION_MODEL` | `VISION_BASE_URL` |
|---|---|---|
| ILMU | `ilmu-vision-v1.3` | — same gateway |
| OpenAI | `gpt-4o-mini` | — same |
| Groq | `llama-3.2-11b-vision-preview` | — same |
| Ollama (local) | `llava` | `http://localhost:11434/v1` |

The URL and key fall back to the chat provider's because the common case is one
gateway serving both, and a repeated URL is one more thing to get out of step.

**Cost.** One vision call per image, once. A 2.5 MP image is roughly 1,500
prompt tokens plus the transcript. There is no per-turn cost afterwards beyond
the text itself.

## How to extend it

**A different vision backend** — implement `ImageReader` (one method: bytes in,
text out) and change one line in `vision/registry.py`.

**A different prompt** — `TRANSCRIBE_PROMPT` in `vision/base.py`. If you are
reading a specific document type, say so there; a prompt that names invoices
transcribes invoices better.

**Re-reading on demand** — the piece this deliberately does not do. It needs the
original bytes kept and a tool that calls the reader with the user's question
instead of the standing prompt. `_read_image()` is where the bytes still exist.

**Safety screening** — there is no hook yet, and for anything public-facing
there should be. The place is `_read_image()` in `document_service.py`, between
`prepare()` and `reader.read()`, so every path to the model is covered by one
check.

## Known limits

- **Images inside documents are still invisible.** A photo in a PDF or `.docx`
  is not extracted or read; only a file that *is* an image gets a vision call.
  Scanned PDFs still fail at upload asking for OCR.
- **The transcript is fixed at upload.** A follow-up needing a fresh look at the
  pixels — "what colour is the third bar?" when the transcript recorded values
  and not colours — cannot be answered. The exhaustive prompt is the mitigation,
  not a fix.
- **No safety screening.** An uploaded image reaches the vision model
  unscreened. Fine for a local or trusted deployment; not fine facing the public
  internet.
- **Transcription quality is the model's.** In testing `ilmu-vision-v1.3` read a
  receipt's every figure correctly and ran two fields together in one reference
  number. Anything quoted back is as good as the model that read it, and no
  worse.
- **Handwriting and low-contrast photos degrade quietly** — they produce a
  plausible transcript rather than an error.
- **HEIC needs Pillow to have been built with it.** The extension is offered;
  the failure, if it comes, is the readable "could not be opened".
- **Animated GIFs are read as their first frame.**
- **The thumbnail is capped** at 64,000 characters; above that the card falls
  back to the file icon.

## Tests

`backend/tests/test_vision.py` — 35 tests:

- **Classification**: images recognised by extension and by media type, the
  no-vision-model refusal naming the real reason, other file kinds unaffected,
  and "or an image" appearing in the supported list only when it is true.
- **Preparation**: re-encoding to JPEG, downscaling to the budget with the
  aspect ratio intact, small images not upscaled, transparency flattened, and
  non-image bytes refused readably. Thumbnails bounded, and `None` rather than
  an error when one cannot be built.
- **The reader** against a mock transport: the image sent as a data URI with the
  transcription prompt at `temperature 0`, control tokens stripped, and each of
  401/404/429/413/500 plus an unreachable host producing a message that says
  what to do about it.
- **The registry**: no model means no reader; the URL and key falling back to
  the chat provider's; an explicit vision endpoint winning.
- **The upload path** against Postgres: an image stored as its transcript, the
  reader handed a JPEG rather than the original, thumbnails present for images
  and absent for text, an image refused without a reader, a vision failure
  keeping its own reason, an unexpected error still refusing readably, an empty
  transcript refused, a corrupt image never reaching the model, and an image
  counting against the three-file limit.

## Verified

A generated receipt (`ilmu-vision-v1.3`, through the same ILMU gateway as chat)
transcribed with every line item, quantity, subtotal, SST and total intact, plus
the `Depicts:` summary. *"What was the total, and which item cost the most?"* →
**"The total was RM 59.36. The item that cost the most was Nasi Lemak Ayam."**
Both correct. The card rendered the thumbnail, and `/api/config` reported
`images_enabled: true`.

# 018 — Document upload

## What it does

Attach a text, PDF or Word file to a chat and ask questions about it. Up to
three files per conversation, 5 MB each, and every attached file stays available
for the whole conversation — so a question can span all three.

Images go through this same path and share these same limits once a vision model
is configured — see [019](019-image-understanding.md).

```
You:  What's the deadline in the brief, and does the contract allow it?
Bot:  The deadline is 14 November 2026, according to project-brief.txt.
      The contract allows 60 days written notice to terminate (contract.txt),
      so the schedule fits.
```

## How it works

### The file becomes text, and the bytes are thrown away

`services/document_extract.py` turns an upload into plain text at the moment it
arrives. The original file is never stored.

| type | read with | unit reported |
|---|---|---|
| `.txt` `.md` `.csv` `.log` `.json` and friends | UTF-8, errors replaced | lines |
| `.pdf` | `pypdf`, page by page | pages |
| `.docx` | `python-docx`, paragraphs **and** table cells | paragraphs |

Classification prefers the **extension** over the browser's media type, because
browsers send `application/octet-stream` for `.md` more often than they send
`text/markdown`.

Storing text rather than bytes is the decision that shapes the rest of the
feature. It means the database holds something small and searchable, a re-read
never re-parses, and a corrupt PDF fails once at upload with a message someone
can act on — rather than at 3am inside a chat turn.

It also means there is no way to show the user the original file, and no way to
re-extract with a better parser later. For a template that trade is right: the
alternative is object storage, which is a service, a bucket policy and a
lifecycle rule that every fork then has to configure.

### Only the relevant part is sent

A 2 MB text file is about 360,000 tokens. No model takes that, and paying to
send it would be absurd even if one did.

`services/document_excerpts.py` splits each document on blank lines into chunks
of roughly twelve lines, scores each chunk by **how many distinct words of the
question it contains**, keeps the highest-scoring chunks that fit the budget,
and restores them to document order. Skipped material is marked `[…]` — without
that marker a model reads two distant passages as consecutive and can invent a
connection between them.

Keyword scoring rather than embeddings, deliberately: no vector column, no
embedding service, no indexing step, nothing to configure, and it works offline.
For *"what does the contract say about termination"* it picks the right
paragraphs. A real retriever can be added later as a second contributor at the
same order without touching this code, which is the point of the pipeline.

### The budget is shared, not first-come

`context/documents.py` divides `DOCUMENTS_TOKEN_BUDGET` evenly across the
attached files. First-come would let one long file consume everything, so a
question about the third file gets answered from nothing — and the user has no
way to see why. Even shares mean the worst case is three shorter excerpts, not
one complete file and two absent ones.

Each file is labelled with its name and length, and a trimmed file says so:

```
--- contract.txt (240 lines — excerpts most relevant to the question) ---
```

That phrase is for the model, not the reader. It is what lets an answer say
"the excerpt does not cover that" instead of asserting something the excerpt
never supported.

### That is the entire integration

`DocumentContributor` sits at **order 350** — the slot the context pipeline has
reserved for retrieval since it was written.

```
100  system prompt
200  memory
300  tool results
350  documents   ← this feature
400  history
500  the user message
```

The chat service loads the conversation's documents and puts them on
`TurnContext`. It has no other knowledge that documents exist: no branch, no
flag, no special case in the turn. A feature landing as one contributor plus one
registry line is the claim the pipeline was built to make, and this is the first
feature to test it.

### A file is pending until a message sends it

A file is uploaded the moment it is picked, which is before there is a message
to hang it on. So `documents.message_id` is null until the user actually sends
something, and `_begin_turn` binds every unbound file in the conversation to the
message it is persisting — in the same transaction, so the composer and the
transcript cannot disagree after a reload.

That one nullable column is the whole state model:

| `message_id` | means | where it shows |
|---|---|---|
| null | picked, not sent | a removable chip in the composer |
| set | sent | a card above that message, permanently |

The card is where a file belongs once it has been sent. Leaving it in the
composer forever makes it look like it never arrived, and gives no answer to
"which question did I attach that to?" three turns later. It has no remove
button: the model has already read the file, and taking the card away would not
take that back.

The limit counts **every** file in the conversation, not the pending ones —
otherwise sending resets the count and a chat can hold any number of files. The
Attach button disables itself at the limit and says why.

Binding is wrapped like every other optional step: if it fails, the file is
still read (the contributor loads by conversation, not by message), so the only
loss is the card. Not worth failing a turn over.

### Attached files suppress pointless web search

Asking "what's the deadline?" with a brief attached should read the brief, not
search Google. `search_intent.decide()` takes `has_documents`, and when files are
present the ambiguous middle defaults to not searching, with the reason shown in
the UI as *answering from the attached files*.

Explicitly time-sensitive wording still searches — "what's the **latest** on
this?" searches even with three files attached, because the files cannot contain
news.

## Errors are answers, not alerts

Every refusal is a message in the chat, in the same place the answer would have
been, saying what happened and what to do:

| situation | message |
|---|---|
| Unsupported type | `notes.key is not a supported file type. Upload plain text, Markdown, CSV, JSON, PDF or Word (.docx).` |
| Too large | `report.pdf is 6.2 MB. The limit is 5 MB per file.` |
| Too many | `This chat already has 3 files, which is the limit. Remove one before adding another.` |
| Empty file | `blank.txt is empty.` |
| Scanned PDF | `No text found in that PDF. Scanned documents need OCR before they can be read.` |
| Corrupt PDF | `That PDF could not be read. It may be corrupt or an unusual format.` |
| Locked PDF | `That PDF is password protected. Remove the password and try again.` |

The size limit is enforced in three places and they have to agree:

1. **The browser**, so nobody waits through a 6 MB upload that was always going
   to be refused.
2. **nginx** (`client_max_body_size 6m`), which is what actually stops the bytes.
   Its default is 1 MB, which rejected a valid 2 MB upload with an HTML error
   page; an `error_page 413` now returns the same JSON envelope as everything
   else, so the client renders it as a chat message rather than as
   `Unexpected token '<'`.
3. **The API**, because a client-side check is a courtesy and not a control.

## Configuration

| variable | default | what it does |
|---|---|---|
| `DOCUMENT_MAX_BYTES` | `5242880` | Per-file limit (5 MB) |
| `DOCUMENT_MAX_PER_CONVERSATION` | `3` | Files per chat |
| `DOCUMENTS_TOKEN_BUDGET` | `8192` | Tokens of document text per turn, shared across files |

Raising `DOCUMENT_MAX_BYTES` means raising `client_max_body_size` in
`frontend/nginx.conf` to match — keep the proxy a little above the API limit so
the JSON error comes from the API and reads better. nginx also spells the limit
out in its own 413 body, because it has no access to the environment; change
both or the two messages will disagree.

`DOCUMENTS_TOKEN_BUDGET` is the cost dial. Every turn in a conversation with
files attached pays it, because the files are re-sent each turn; 8192 tokens is
roughly $0.001 per turn on GPT-4o-mini and about $0.02 on a frontier model.

## How to extend it

**A new file type** — add a branch to `classify()` and a reader to
`document_extract.py` returning `ExtractedText(text, unit, count)`. Nothing else
changes; the excerpt selector and the contributor work on text.

**Real retrieval** — write a second contributor at order 350 that embeds chunks
and queries a vector store, and register it instead of this one. The prompt
shape, the UI, the limits and the error messages all stay.

**Removing a sent file** — the endpoint exists
(`DELETE /api/conversations/{id}/documents/{doc_id}`) and the composer chips
call it for pending files. Wiring it to the transcript cards is a UI change
only; the foreign key is `ON DELETE SET NULL`, so the file survives its message
being deleted.

**Keeping the original bytes** — add a column or an object-storage key next to
the extracted text. Nothing reads the original today, so nothing breaks.

## Known limits

- **Text only.** Images, charts and diagrams inside a PDF are invisible; the
  model sees whatever text surrounds them. A slide deck of pictures extracts to
  almost nothing.
- **Scanned PDFs need OCR**, which is not included. They fail at upload with a
  message saying so, which is better than silently attaching a blank file.
- **Layout is lost.** A two-column PDF extracts in reading order as `pypdf` sees
  it, which for some documents interleaves the columns. Tables in a PDF become
  runs of numbers; tables in a `.docx` survive, because `python-docx` exposes
  cells.
- **Keyword matching misses synonyms.** A question about "notice period" scores
  a paragraph headed "Termination" no higher than any other, unless the word
  appears. This is the ceiling of the approach and the reason the retrieval slot
  is designed to be replaceable.
- **No cross-file ranking.** Each file gets an equal share of the budget even
  when the question is plainly about one of them. Even shares are predictable
  and prevent starvation; proportional shares would need to decide relevance
  before reading, which is the problem being solved.
- **Files are re-sent every turn.** There is no caching of the excerpt between
  turns, so a long conversation over three files pays the document budget each
  time. A file attached at turn one is still read at turn ten — which is the
  feature, and also the cost.
- **A card cannot be removed from the transcript.** Deleting the file is
  possible through the API; the UI only offers it while the file is pending.
- **The original file cannot be downloaded back**, because it is not kept.
- **No virus scanning.** Text is extracted, never executed, and the bytes are
  discarded — but a fork exposing this to the public internet should put a
  scanner in front of it.
- **Extraction is synchronous.** A 5 MB PDF holds its request for a second or
  two. For a template that is acceptable; a queue is the answer if uploads get
  bigger.

## Tests

`backend/tests/test_documents.py` — 49 tests:

- **Classification** by extension over media type, including the
  `octet-stream` `.md` case, and unsupported types naming themselves.
- **Extraction** of text, PDF (against a hand-built structurally valid PDF, so
  the fixture needs no writer library and cannot drift when one is upgraded),
  invalid UTF-8, collapsed blank runs, a corrupt PDF, and a text-free PDF
  mentioning OCR.
- **Excerpt selection**: a short document passed through whole, a long one
  yielding the matching section, the same document answering two questions
  differently, document order preserved, skip markers, a budget smaller than any
  single chunk still yielding text, a zero budget, and stopword filtering.
- **The contributor**: no documents contributing nothing, files labelled by
  name, the budget shared so a short second file survives a long first one,
  trimmed files saying so, and the order being 350.
- **The service** against Postgres: storage with extracted text, both sizes named
  in the oversize error, the file-count limit, empty files, unsupported types,
  another user's conversation returning not-found, listing oldest first, deletion
  freeing a slot, and deleting someone else's file returning not-found.
- **Binding**: a new file belonging to no message, sending binding every pending
  file, a second send leaving the first message's cards alone, sending nothing
  binding nothing, a sent file still counting against the limit, and a sent file
  still being read on later turns.

`frontend/src/lib/api.test.ts` — `FormData` must not get a JSON content type.
Forcing one destroys the multipart boundary and the server rejects the upload
with a 422 that says nothing useful.

## Verified

A text file and a PDF attached to one chat, then: *"What's the revenue, and how
much notice to terminate?"* → **"Revenue: RM 42 million, according to
report.pdf. Notice to terminate: 60 days written notice, according to
contract.txt."**

All three limit errors rendered in the chat. A 2.1 MB file (360,000 tokens)
correctly surfaced its payment-terms paragraph alongside a second file. With
files attached, "what is the deadline?" answered from the file without searching;
"what's the latest on this?" still searched.

Cards were verified **after a reload**, which is a different code path from the
live one and is where this class of bug hides: two files attached at different
points in one chat came back on their own messages rather than both on the
newest, the composer came back empty, and Attach was disabled at the limit with
"This chat has reached its file limit".

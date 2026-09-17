# 007 — Message actions

## What it does

Hover actions under every finished assistant message: copy, regenerate, and
thumbs up/down with an optional reason.

## How it works

### Copy

`navigator.clipboard.writeText` on the message's raw markdown, not the rendered
DOM — pasting into a document should give you the source, not flattened text.
The icon becomes a tick for 1.6s. Clipboard permission can be denied, in which
case nothing happens rather than an alert nobody can act on.

### Regenerate

`POST /api/chat/stream` with `{"regenerate_of": "<assistant message id>"}` and
no content. The service finds the question above that answer, **reuses the same
row** (clearing content and finish_reason), and streams a new response.

Reusing the row rather than deleting and inserting keeps the id stable for
anything referencing it, and keeps scroll position steady in the UI.

Only the most recent answer can be regenerated. Redoing an earlier one would
orphan every exchange after it, and silently deleting a conversation's tail is
not something a button should do. Attempting it returns *Only the latest
response can be regenerated.*

Existing feedback on the message is cleared on regeneration — a rating applies
to an answer, and that answer no longer exists.

### Thumbs

`PUT /api/chat/messages/{id}/feedback` with `{rating, reason}`. A unique
constraint on `(message_id, user_id)` means rating again **replaces** rather
than appends, so the table answers "what does this person think of this answer
now?" rather than "what have they clicked over time". Clicking the active thumb
clears the rating (`DELETE`).

A thumbs-down opens a one-line reason box. The reasons are the point — counts
tell you something is wrong, reasons tell you what. It is skippable, because a
mandatory field turns a one-click signal into a decision.

Ratings are returned with the conversation rather than as a second request, so
the thumbs render in their correct state on first paint instead of popping in.

Only assistant messages can be rated; rating a user message returns *Only
assistant messages can be rated.*

## Configuration

None. Actions are always available.

## How to extend it

- **Edit and resend a user message**: the regeneration path already handles
  "replace this message and re-answer"; the user-message variant needs to delete
  the turns after it, which is why it is not here.
- **Answer versions**: regeneration currently overwrites. Keeping history means a
  `message_versions` table and a switcher in `MessageActions`.
- **More actions**: `MessageActions` is a flat list of `ActionButton`s.

## Known limits

- **Regeneration is destructive.** The previous answer is gone, with no undo.
- **Only the latest answer** can be regenerated, by design.
- **Copy needs a secure context.** `navigator.clipboard` is unavailable over
  plain http on a non-localhost origin, and the button silently does nothing.
- **Feedback is per user, not per organisation.** There is no aggregate view;
  reading it means `SELECT rating, reason FROM message_feedback`.
- **Actions appear only after streaming ends**, so you cannot copy a partial
  answer while it is being written.

## Verified

Regeneration streamed 45 new tokens into the same row and produced different
content. Regenerating an earlier answer and a user message were both refused.
Re-rating replaced rather than duplicated, and a reload showed the current
rating.

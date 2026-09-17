# 008 — Markdown export

## What it does

Downloads a conversation as a Markdown file.

## How it works

`GET /api/conversations/{id}/export` returns `text/markdown; charset=utf-8` with
a `Content-Disposition: attachment` header. The frontend is a plain `<a download>`
— the browser already knows how to save a file the server marked as an
attachment, so there is no reason to fetch it into a blob and synthesise a click.

The document carries a title, an export timestamp, a horizontal rule, then each
turn under a `## You` / `## Assistant` heading. Messages that were stopped early
are marked `*(stopped early)*`, because a truncated answer that looks complete in
an export is worse than no export.

Markdown rather than JSON or PDF: readable as plain text, pastes into almost
anything, and survives being opened in ten years by something that does not
exist yet.

### Filenames

Built from the title — lowercased, punctuation stripped, spaces hyphenated,
truncated to 60 characters — with the first 8 characters of the id appended. The
title makes a folder of exports browsable; the id suffix keeps two conversations
with the same title apart.

```
write-a-haiku-about-lanterns-then-explain-it-in-one-bf97e5e0.md
```

## Configuration

`APP_NAME` appears in the export's byline. Nothing else.

## How to extend it

`to_markdown()` is a pure function over a `Conversation`. A JSON or HTML export
is a sibling function and one more route. Adding per-message metadata — token
counts, model, sources — means extending `_render`.

## Known limits

- **No bulk export.** One conversation per request.
- **Sources, token counts and ratings are not included.** Only the conversation.
- **Nothing is redacted.** The export contains exactly what was said.
- **Loaded fully into memory.** Fine at chat sizes; a conversation of hundreds of
  thousands of tokens would want streaming.

## Verified

Correct `Content-Type` and `Content-Disposition`, slugged filename with id
suffix, and a readable document.

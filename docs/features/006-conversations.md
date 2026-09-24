# 006 — Conversation history

## What it does

A sidebar of past conversations grouped by recency, with rename and delete. New
conversations appear the moment a stream starts rather than after the answer
finishes, and get a title derived from the first message instead of sitting as
"New chat" while you read.

## How it works

### Ownership is part of the lookup

`ConversationRepository.get(conversation_id, user_id)` takes the user id rather
than leaving the caller to check afterwards. There is no code path that can
forget the check, and a conversation belonging to someone else returns the same
404 as one that does not exist — so the endpoint cannot be used to discover
which ids are real.

### Grouping

`groupByRecency` buckets into Today, Yesterday, Previous 7 days, Previous 30
days and Older, comparing against local midnight rather than a rolling 24 hours.
A message sent at 00:30 belongs to "Today", which is what a person means by the
word.

Empty buckets are dropped, so a new account sees one heading rather than five.

### Optimistic updates

Rename and delete update local state first and reconcile on failure by
refetching. `upsert` inserts a conversation at the top of the list when a stream
starts, so the sidebar reflects reality before the round trip finishes.

The sidebar failing to load does not take the chat with it — `useConversations`
catches and renders an empty list.

### Titles

Derived from the first message: whitespace collapsed, cut at 60 characters on a
word boundary where one falls past the halfway mark, trailing punctuation
stripped, ellipsis appended.

No model call. A title is worth one string operation, not a round trip and a
failure mode on every new conversation. Renaming is one click for the cases
where it matters.

## Endpoints

| method | path | purpose |
|---|---|---|
| `GET` | `/api/conversations` | Paged, newest first. `limit` (≤200), `offset` |
| `GET` | `/api/conversations/{id}` | With all messages |
| `PATCH` | `/api/conversations/{id}` | Rename |
| `DELETE` | `/api/conversations/{id}` | Cascades to messages |

## How to extend it

- **Search**: add a `q` parameter and an index. Postgres full-text over
  `messages.content` is the obvious version.
- **Archiving**: the `archived` column exists and is already excluded from the
  list query; it needs an endpoint and a UI affordance.
- **Folders or sharing**: a join table and a filter on the list query. The
  ownership check stays where it is.

## Known limits

- **No pagination in the UI.** The sidebar requests 100 and stops. Past that,
  older conversations are reachable only by URL. The endpoint pages properly;
  the UI does not use it yet.
- **Delete is immediate and permanent.** No confirmation dialog and no undo.
  `ON DELETE CASCADE` removes the messages with it.
- **No search**, so finding an old conversation means scrolling.
- **Titles come from the first message**, which is a poor summary when the first
  message is "hi".
- **The list is not live.** A conversation created in another tab appears after a
  refresh.

## Tests

Covered by `backend/tests/test_layering.py` (the repository and service stay
free of FastAPI imports) and exercised end to end in the browser: conversations
appear grouped under Today, the active one is highlighted, selecting one loads
its messages, and a deleted conversation returns to the empty state.

## Minimising the sidebar

From md up the sidebar folds to a 60px rail -- a way back, a new chat, and the
account -- with the minimise button beside **New chat**. The conversation list
is the part that takes room, and it is one click away. The choice is
remembered in the browser, because a sidebar that springs back open on every
reload is one somebody has to fold again every time. On a phone the sidebar is
already a drawer, and folding it would only hide the button that opens it, so
it is unaffected.

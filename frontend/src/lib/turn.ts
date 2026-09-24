/**
 * How to get a turn's events from the server.
 *
 * There are two ways in and they matter equally. `start` asks for a new turn.
 * `follow` picks up one that is already running — after a reload, after
 * switching back from another conversation, or after the connection dropped
 * while a build was still minutes from finishing.
 *
 * The second one only became possible when the server stopped tying a turn to
 * the request that asked for it. Before that, losing the connection lost the
 * work, and because an artifact is stored only once it is finished, there was
 * nothing left to come back to.
 */

import type { StreamBody } from '@/lib/chat-types'

export type Opening =
  | { kind: 'start'; body: StreamBody }
  | { kind: 'follow'; conversation: string }

/**
 * How many times to rejoin a turn whose connection went away.
 *
 * A handful, not unlimited: a turn that keeps dropping is a turn something is
 * genuinely wrong with, and retrying it forever hides that behind a spinner
 * that never stops.
 */
export const REJOINS = 3

/** How long to wait before rejoining, per attempt. */
export function pauseBefore(attempt: number): number {
  return Math.min(500 * 2 ** attempt, 4000)
}

/**
 * Open the stream.
 *
 * `null` means there was nothing to follow — the ordinary answer when a
 * conversation simply has no turn running in it, and not worth reporting. The
 * server says so with a 204 rather than a 404, because a browser logs every
 * 4xx as a console error and this is asked of every conversation opened.
 */
export async function openTurn(
  opening: Opening,
  signal: AbortSignal,
): Promise<Response | null> {
  if (opening.kind === 'follow') {
    const response = await fetch(`/api/chat/live/${opening.conversation}`, { signal })
    return response.status === 204 || response.status === 404 ? null : response
  }
  return fetch('/api/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...opening.body, timezone: opening.body.timezone ?? localZone() }),
    signal,
  })
}

/**
 * Where the person is, as the browser knows it.
 *
 * Sent with every turn, because the server's clock says what time it is in
 * UTC and "what is today's date?" asked at 07:00 in Kuala Lumpur is still
 * yesterday there.
 */
export function localZone(): string | undefined {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || undefined
  } catch {
    return undefined
  }
}

/**
 * Why the server would not start the turn.
 *
 * The body carries the actual reason — which allowance ran out, how much was
 * used — and "the server refused the request (429)" throws all of that away at
 * exactly the moment someone needs it.
 */
export async function refusalMessage(response: Response): Promise<string> {
  if (response.status === 401) return 'Your session expired. Sign in again.'
  try {
    const body = (await response.json()) as { error?: { message?: string } }
    if (body?.error?.message) return body.error.message
  } catch {
    // Not our envelope — a proxy error page, say.
  }
  return `The server refused the request (${response.status}).`
}

/** An abort is the stop button working, or a component going away. Not a failure. */
export function wasAborted(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}

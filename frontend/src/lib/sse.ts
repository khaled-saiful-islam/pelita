/**
 * Minimal SSE reader over `fetch`.
 *
 * `EventSource` cannot POST and cannot send a JSON body, and the chat endpoint
 * needs both, so the framing is parsed by hand. It is about fifty lines and
 * removes a dependency that would not have fit anyway.
 */

export interface SseMessage {
  event: string
  data: string
}

/**
 * Frame and line separators.
 *
 * The spec permits CRLF, LF and a lone CR, and servers genuinely differ:
 * `sse-starlette`, which this backend uses, emits CRLF. Matching only `\n\n`
 * parses nothing at all against it — and because the request still returns 200
 * and logs no error, the failure looks like an empty response rather than a
 * parse bug.
 */
const FRAME_BOUNDARY = /\r\n\r\n|\n\n|\r\r/
const LINE_BOUNDARY = /\r\n|\n|\r/

export async function* readSse(
  body: ReadableStream<Uint8Array>,
  signal?: AbortSignal,
): AsyncGenerator<SseMessage> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      if (signal?.aborted) return
      const { done, value } = await reader.read()
      if (done) break

      // `stream: true` keeps multi-byte characters intact across chunks.
      buffer += decoder.decode(value, { stream: true })

      // A chunk boundary can fall anywhere, including mid-frame, so complete
      // frames are drained and the remainder is kept for the next read.
      while (true) {
        const match = FRAME_BOUNDARY.exec(buffer)
        if (!match) break
        const frame = buffer.slice(0, match.index)
        buffer = buffer.slice(match.index + match[0].length)
        const parsed = parseFrame(frame)
        if (parsed) yield parsed
      }
    }

    // A final frame with no trailing blank line still counts.
    const tail = parseFrame(buffer)
    if (tail) yield tail
  } finally {
    reader.releaseLock()
  }
}

function parseFrame(frame: string): SseMessage | null {
  let event = 'message'
  const dataLines: string[] = []

  for (const line of frame.split(LINE_BOUNDARY)) {
    if (line.startsWith(':')) continue // comment, used for keep-alive pings
    const colon = line.indexOf(':')
    if (colon === -1) continue
    const field = line.slice(0, colon)
    // A single leading space after the colon is framing, not data.
    const value = line.slice(colon + 1).replace(/^ /, '')

    if (field === 'event') event = value
    else if (field === 'data') dataLines.push(value)
  }

  if (dataLines.length === 0) return null
  return { event, data: dataLines.join('\n') }
}

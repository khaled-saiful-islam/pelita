import { describe, expect, it } from 'vitest'
import { readSse } from './sse'

/** A body that hands back exactly the chunks given, to control split points. */
function bodyOf(...chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
      controller.close()
    },
  })
}

async function collect(stream: ReadableStream<Uint8Array>) {
  const out = []
  for await (const message of readSse(stream)) out.push(message)
  return out
}

describe('readSse', () => {
  it('parses CRLF framing, which is what sse-starlette emits', async () => {
    // Regression: matching only "\n\n" parsed nothing against a CRLF server,
    // and the request still returned 200, so it looked like an empty response.
    const messages = await collect(
      bodyOf('event: start\r\ndata: {"a":1}\r\n\r\nevent: token\r\ndata: {"text":"hi"}\r\n\r\n'),
    )
    expect(messages).toEqual([
      { event: 'start', data: '{"a":1}' },
      { event: 'token', data: '{"text":"hi"}' },
    ])
  })

  it('parses LF framing too', async () => {
    const messages = await collect(bodyOf('event: token\ndata: {"text":"hi"}\n\n'))
    expect(messages).toEqual([{ event: 'token', data: '{"text":"hi"}' }])
  })

  it('reassembles a frame split across chunks', async () => {
    const messages = await collect(bodyOf('event: tok', 'en\r\ndata: {"text', '":"hi"}\r\n\r\n'))
    expect(messages).toEqual([{ event: 'token', data: '{"text":"hi"}' }])
  })

  it('handles a chunk boundary falling inside the frame separator', async () => {
    const messages = await collect(bodyOf('event: a\r\ndata: 1\r', '\n\r\nevent: b\r\ndata: 2\r\n\r\n'))
    expect(messages.map((m) => m.event)).toEqual(['a', 'b'])
  })

  it('survives a multi-byte character split across chunks', async () => {
    // "世" is three bytes; the split lands in the middle of it.
    const encoded = new TextEncoder().encode('data: 世界\r\n\r\n')
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoded.slice(0, 8))
        controller.enqueue(encoded.slice(8))
        controller.close()
      },
    })
    const messages = await collect(stream)
    expect(messages).toEqual([{ event: 'message', data: '世界' }])
  })

  it('ignores keep-alive comment frames', async () => {
    const messages = await collect(bodyOf(': ping - 2026-01-01\r\n\r\ndata: real\r\n\r\n'))
    expect(messages).toEqual([{ event: 'message', data: 'real' }])
  })

  it('joins multi-line data with newlines, per the spec', async () => {
    const messages = await collect(bodyOf('data: one\r\ndata: two\r\n\r\n'))
    expect(messages).toEqual([{ event: 'message', data: 'one\ntwo' }])
  })

  it('emits a trailing frame that has no blank line after it', async () => {
    const messages = await collect(bodyOf('event: done\r\ndata: {}'))
    expect(messages).toEqual([{ event: 'done', data: '{}' }])
  })

  it('stops when the signal aborts', async () => {
    const controller = new AbortController()
    controller.abort()
    const out = []
    for await (const m of readSse(bodyOf('data: x\r\n\r\n'), controller.signal)) out.push(m)
    expect(out).toEqual([])
  })
})

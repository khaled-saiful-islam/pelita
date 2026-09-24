/**
 * Leaving a build and coming back.
 *
 * An artifact is stored only once it is finished, so for the minutes before
 * that the half-written answer and the build on it exist in this hook and
 * nowhere else. Every way of losing them looks the same to the person: they
 * come back to the conversation they were watching and find the question with
 * no answer under it.
 */

import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useChat } from './useChat'

const encoder = new TextEncoder()

function frame(event: string, data: unknown): string {
  return `event: ${event}\r\ndata: ${JSON.stringify(data)}\r\n\r\n`
}

/** A response whose body this test feeds, a frame at a time. */
function live() {
  let controller!: ReadableStreamDefaultController<Uint8Array>
  const body = new ReadableStream<Uint8Array>({
    start: (c) => {
      controller = c
    },
  })
  return {
    response: new Response(body, { status: 200 }),
    send: (event: string, data: unknown) => controller.enqueue(encoder.encode(frame(event, data))),
    end: () => controller.close(),
    /** The connection going away under a turn that is still running. */
    drop: () => controller.error(new TypeError('network error')),
  }
}

const POSTER = {
  conversation_id: 'conv-poster',
  user_message_id: 'user-1',
  assistant_message_id: 'answer-1',
  title: 'A poster',
  language: 'en',
}

function conversation(id: string, messages: unknown[] = []) {
  return {
    id,
    title: id,
    messages,
    feedback: {},
    language: 'en',
    totals: null,
  }
}

interface Server {
  /** Conversations as the database has them: no in-flight answer in here. */
  stored: Record<string, ReturnType<typeof conversation>>
  /** The turn this server is running, if any. */
  turn: ReturnType<typeof live> | null
  /** Whether `GET /chat/live/{id}` finds something to follow. */
  liveFor: string | null
  calls: string[]
}

function serve(server: Server) {
  vi.stubGlobal('fetch', async (input: RequestInfo | URL) => {
    const url = String(input)
    server.calls.push(url)

    if (url === '/api/chat/stream') return server.turn!.response
    if (url.startsWith('/api/chat/live/')) {
      const id = url.slice('/api/chat/live/'.length)
      if (server.liveFor !== id) return new Response(null, { status: 204 })
      return server.turn!.response
    }
    const artifacts = url.match(/^\/api\/conversations\/(.+)\/artifacts$/)
    if (artifacts) return Response.json({ items: [] })
    const detail = url.match(/^\/api\/conversations\/(.+)$/)
    if (detail) return Response.json(server.stored[detail[1]] ?? conversation(detail[1]))
    throw new Error(`unstubbed ${url}`)
  })
}

afterEach(() => vi.unstubAllGlobals())

describe('a build in progress', () => {
  it('is still there after reading another conversation and coming back', async () => {
    const turn = live()
    const server: Server = {
      stored: { 'conv-poster': conversation('conv-poster'), other: conversation('other') },
      turn,
      liveFor: null,
      calls: [],
    }
    serve(server)

    const { result } = renderHook(() => useChat())

    await act(async () => {
      void result.current.send('make me a poster')
      await Promise.resolve()
    })

    await act(async () => {
      turn.send('start', POSTER)
      turn.send('artifact.start', { kind: 'poster', title: 'Night market' })
      turn.send('artifact.step', { label: 'Choosing a direction', detail: '' })
      await new Promise((go) => setTimeout(go, 0))
    })

    await waitFor(() => expect(result.current.messages.at(-1)?.building).toBeTruthy())

    // Away — and the build keeps going while we are gone.
    await act(async () => {
      await result.current.load('other')
    })
    expect(result.current.messages).toHaveLength(0)

    await act(async () => {
      turn.send('artifact.design', {
        movement: 'Tropical modernism',
        palette: ['#0b3d2e', '#f4e7c3'],
        display_font: 'Instrument Serif',
        body_font: 'Inter',
        rationale: 'A night market is a graft of cultures under fluorescent light.',
        width: 1080,
        height: 1350,
      })
      await new Promise((go) => setTimeout(go, 0))
    })

    // Back. The answer, the card, and everything that landed while away.
    await act(async () => {
      await result.current.load('conv-poster')
    })

    const answer = result.current.messages.at(-1)
    expect(answer?.id).toBe('answer-1')
    expect(answer?.building?.kind).toBe('poster')
    expect(answer?.building?.steps).toHaveLength(1)
    expect(answer?.building?.design?.movement).toBe('Tropical modernism')
    expect(result.current.streaming).toBe(true)

    await act(async () => {
      turn.end()
    })
  })

  it('is picked back up from the server when this tab was not the one running it', async () => {
    // What a reload leaves behind: the turn is running on the server and this
    // client knows nothing about it. Everything it has already said is
    // replayed, so the panel fills in rather than starting from the middle.
    const turn = live()
    const server: Server = {
      stored: {
        'conv-poster': conversation('conv-poster', [
          {
            id: 'user-1',
            role: 'user',
            content: 'make me a poster',
            created_at: new Date().toISOString(),
            finish_reason: null,
            model: null,
            prompt_tokens: 0,
            completion_tokens: 0,
            cost: 0,
            usage_source: null,
          },
        ]),
      },
      turn,
      liveFor: 'conv-poster',
      calls: [],
    }
    serve(server)

    const { result } = renderHook(() => useChat())

    await act(async () => {
      await result.current.load('conv-poster')
    })

    await act(async () => {
      turn.send('start', POSTER)
      turn.send('artifact.start', { kind: 'poster', title: 'Night market' })
      turn.send('artifact.step', { label: 'Writing it', detail: '' })
      await new Promise((go) => setTimeout(go, 0))
    })

    await waitFor(() => {
      const answer = result.current.messages.at(-1)
      expect(answer?.building?.title).toBe('Night market')
    })
    expect(result.current.messages).toHaveLength(2)
    expect(result.current.streaming).toBe(true)

    await act(async () => {
      turn.end()
    })
  })

  it('does not ask the server to follow a turn this tab is already reading', async () => {
    const turn = live()
    const server: Server = {
      stored: { 'conv-poster': conversation('conv-poster') },
      turn,
      liveFor: 'conv-poster',
      calls: [],
    }
    serve(server)

    const { result } = renderHook(() => useChat())
    await act(async () => {
      void result.current.send('make me a poster')
      await Promise.resolve()
    })
    await act(async () => {
      turn.send('start', POSTER)
      await new Promise((go) => setTimeout(go, 0))
    })

    server.calls.length = 0
    await act(async () => {
      await result.current.load('conv-poster')
    })

    // Following it twice would deliver every token twice.
    expect(server.calls.filter((url) => url.startsWith('/api/chat/live/'))).toHaveLength(0)

    await act(async () => {
      turn.end()
    })
  })
})

describe('a connection that drops mid-build', () => {
  it('rejoins the turn instead of losing it', async () => {
    // The one that actually bites: a browser suspends a socket held open for
    // minutes on a backgrounded tab. The turn is fine — it runs on the server
    // — but the client used to treat the dropped socket as the end of it.
    const first = live()
    const second = live()
    const server: Server = {
      stored: { 'conv-poster': conversation('conv-poster') },
      turn: first,
      liveFor: 'conv-poster',
      calls: [],
    }
    serve(server)

    const { result } = renderHook(() => useChat())
    await act(async () => {
      void result.current.send('make me a poster')
      await Promise.resolve()
    })
    await act(async () => {
      first.send('start', POSTER)
      first.send('artifact.start', { kind: 'poster', title: 'Night market' })
      await new Promise((go) => setTimeout(go, 0))
    })

    server.turn = second
    await act(async () => {
      first.drop()
      await new Promise((go) => setTimeout(go, 700))
    })

    expect(server.calls).toContain('/api/chat/live/conv-poster')

    // Replayed from the first event, so the card is whole rather than starting
    // from whatever happened to come next.
    await act(async () => {
      second.send('start', POSTER)
      second.send('artifact.start', { kind: 'poster', title: 'Night market' })
      second.send('artifact.step', { label: 'Writing it', detail: '' })
      await new Promise((go) => setTimeout(go, 0))
    })

    await waitFor(() => {
      expect(result.current.messages.at(-1)?.building?.steps).toHaveLength(1)
    })
    expect(result.current.error).toBeNull()
    expect(result.current.messages.filter((m) => m.role === 'assistant')).toHaveLength(1)

    await act(async () => {
      second.end()
    })
  })

  it('does not ask again when the server refused the turn outright', async () => {
    vi.stubGlobal('fetch', async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/api/chat/stream') {
        return new Response(JSON.stringify({ error: { message: 'You are out of credit.' } }), {
          status: 429,
        })
      }
      throw new Error(`unstubbed ${url}`)
    })

    const { result } = renderHook(() => useChat())
    await act(async () => {
      await result.current.send('make me a poster')
    })

    expect(result.current.error).toBe('You are out of credit.')
    expect(result.current.streaming).toBe(false)
  })
})

describe('the hook\'s identity', () => {
  it('keeps load and reset stable across renders', async () => {
    // The page reloads the conversation in an effect keyed on these, and that
    // effect calls reset() when there is no conversation in the route — which
    // aborts the stream. A load() that changed identity on every render
    // therefore killed the turn it had just started, and the message vanished
    // with it. Nothing about the transcript makes this visible; only the
    // identity does.
    const server: Server = {
      stored: { 'conv-poster': conversation('conv-poster') },
      turn: null,
      liveFor: null,
      calls: [],
    }
    serve(server)

    const { result, rerender } = renderHook(() => useChat(() => {}))
    const first = { load: result.current.load, reset: result.current.reset }

    rerender()
    await act(async () => {
      await result.current.load('conv-poster')
    })
    rerender()

    expect(result.current.load).toBe(first.load)
    expect(result.current.reset).toBe(first.reset)
  })
})

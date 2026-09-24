import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useAppState } from './useAppState'

interface Call {
  url: string
  method: string
  body?: string
}

function server(saved: unknown) {
  const calls: Call[] = []
  vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
    const call = { url: String(input), method: init?.method ?? 'GET', body: init?.body as string }
    calls.push(call)
    if (call.method === 'GET') return Response.json({ data: saved })
    return new Response(null, { status: 204 })
  })
  return calls
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('useAppState', () => {
  it('opens the app with what this person saved last time', async () => {
    server({ tasks: ['Water the plants'] })
    const { result } = renderHook(() => useAppState('app-1'))
    await waitFor(() => expect(result.current.ready).toBe(true))
    expect(result.current.current()).toEqual({ tasks: ['Water the plants'] })
  })

  it('batches saves into one, however often the app asks', async () => {
    const calls = server(null)
    const { result } = renderHook(() => useAppState('app-1'))
    await waitFor(() => expect(result.current.ready).toBe(true))

    vi.useFakeTimers()
    act(() => {
      result.current.save('{"tasks":["a"]}')
      result.current.save('{"tasks":["a","b"]}')
      result.current.save('{"tasks":["a","b","c"]}')
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(700)
    })

    const puts = calls.filter((c) => c.method === 'PUT')
    expect(puts).toHaveLength(1)
    expect(JSON.parse(puts[0].body!)).toEqual({ data: { tasks: ['a', 'b', 'c'] } })
  })

  it('opens a new version with what was saved a minute ago, not what was loaded', async () => {
    // A change made in the chat arrives mid-session as a new document. It must
    // not open with the tasks as they were before the last few were typed.
    server({ tasks: [] })
    const { result } = renderHook(() => useAppState('app-1'))
    await waitFor(() => expect(result.current.ready).toBe(true))
    act(() => result.current.save('{"tasks":["typed just now"]}'))
    expect(result.current.current()).toEqual({ tasks: ['typed just now'] })
  })

  it('starts over by clearing what it saved and opening a fresh document', async () => {
    const calls = server({ tasks: ['old'] })
    const { result } = renderHook(() => useAppState('app-1'))
    await waitFor(() => expect(result.current.ready).toBe(true))
    const before = result.current.nonce

    await act(async () => {
      await result.current.reset()
    })

    expect(calls.some((c) => c.method === 'DELETE' && c.url.endsWith('/artifacts/app-1/state'))).toBe(true)
    expect(result.current.nonce).toBe(before + 1)
    expect(result.current.current()).toBeNull()
  })

  it('refuses to send more than an app may keep', async () => {
    const calls = server(null)
    const { result } = renderHook(() => useAppState('app-1'))
    await waitFor(() => expect(result.current.ready).toBe(true))
    act(() => result.current.save(JSON.stringify({ rows: 'x'.repeat(300 * 1024) })))
    expect(result.current.error).toMatch(/more than it is allowed/)
    expect(calls.filter((c) => c.method === 'PUT')).toHaveLength(0)
  })
})

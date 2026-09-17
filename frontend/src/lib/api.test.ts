import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, apiFetch } from './api'

function mockFetch(response: Response) {
  const spy = vi.fn().mockResolvedValue(response)
  vi.stubGlobal('fetch', spy)
  return spy
}

afterEach(() => vi.unstubAllGlobals())

describe('apiFetch', () => {
  it('prefixes /api so call sites never repeat it', async () => {
    const spy = mockFetch(new Response('{"ok":true}', { status: 200 }))
    await apiFetch('/config')
    expect(spy).toHaveBeenCalledWith('/api/config', expect.anything())
  })

  it('unwraps the error envelope into a readable message', async () => {
    mockFetch(
      new Response(JSON.stringify({ error: { code: 'not_found', message: 'No such chat' } }), {
        status: 404,
      }),
    )
    await expect(apiFetch('/conversations/x')).rejects.toMatchObject({
      message: 'No such chat',
      status: 404,
      code: 'not_found',
    })
  })

  it('falls back to a generic message when the body is not our envelope', async () => {
    // A proxy 502 is HTML, not JSON. The UI still needs something to show.
    mockFetch(new Response('<html>Bad Gateway</html>', { status: 502 }))
    const error = await apiFetch('/chat').catch((e: ApiError) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).message).toBe('Request failed (502)')
  })

  it('sets a JSON content type only when there is a body', async () => {
    // A Response body can only be read once, so each call needs its own.
    const spy = vi.fn().mockImplementation(async () => new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', spy)

    await apiFetch('/a')
    expect(spy.mock.calls[0][1].headers).not.toHaveProperty('Content-Type')

    await apiFetch('/b', { method: 'POST', body: '{}' })
    expect(spy.mock.calls[1][1].headers).toHaveProperty('Content-Type', 'application/json')
  })

  it('returns undefined for 204 instead of failing to parse an empty body', async () => {
    mockFetch(new Response(null, { status: 204 }))
    await expect(apiFetch('/memories/1')).resolves.toBeUndefined()
  })
})

describe('apiFetch content type', () => {
  it('does not set a JSON content type for FormData', async () => {
    // The browser generates the multipart boundary; overriding the header
    // leaves the server unable to parse the upload at all.
    const spy = vi.fn().mockResolvedValue(new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', spy)

    const body = new FormData()
    body.append('file', new Blob(['x']), 'x.txt')
    await apiFetch('/upload', { method: 'POST', body })

    expect(spy.mock.calls[0][1].headers).not.toHaveProperty('Content-Type')
  })
})

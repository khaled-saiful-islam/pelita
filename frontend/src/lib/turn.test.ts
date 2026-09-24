import { afterEach, describe, expect, it, vi } from 'vitest'
import { localZone, openTurn } from '@/lib/turn'

describe('openTurn', () => {
  afterEach(() => vi.unstubAllGlobals())

  it("sends the person's own zone with every new turn", async () => {
    const fetched = vi.fn().mockResolvedValue(new Response(null, { status: 200 }))
    vi.stubGlobal('fetch', fetched)

    await openTurn({ kind: 'start', body: { content: 'what is the date?' } }, new AbortController().signal)

    const body = JSON.parse(fetched.mock.calls[0][1].body as string)
    expect(body.timezone).toBe(localZone())
    expect(body.content).toBe('what is the date?')
  })

  it('keeps a zone the caller gave', async () => {
    const fetched = vi.fn().mockResolvedValue(new Response(null, { status: 200 }))
    vi.stubGlobal('fetch', fetched)

    await openTurn(
      { kind: 'start', body: { regenerate_of: 'm1', timezone: 'Asia/Kuala_Lumpur' } },
      new AbortController().signal,
    )

    expect(JSON.parse(fetched.mock.calls[0][1].body as string).timezone).toBe('Asia/Kuala_Lumpur')
  })
})

describe('localZone', () => {
  it('is a zone name the server can look up', () => {
    expect(localZone()).toMatch(/^[A-Za-z_]+(\/[A-Za-z0-9_+-]+)*$/)
  })
})

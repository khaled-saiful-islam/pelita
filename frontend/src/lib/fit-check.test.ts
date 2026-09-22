import { describe, expect, it, vi } from 'vitest'
import { checkFit } from './fit-check'

/**
 * jsdom does not lay anything out, so these cover the parts that are ours: the
 * frame's permissions, who is allowed to answer it, and what happens when
 * nothing does. The measurement itself is checked against a real browser.
 */
describe('checkFit', () => {
  it('measures in a frame that cannot reach the app', async () => {
    const created: HTMLIFrameElement[] = []
    const realCreate = document.createElement.bind(document)
    vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      const el = realCreate(tag)
      if (tag === 'iframe') created.push(el as HTMLIFrameElement)
      return el
    })

    const pending = checkFit('<html></html>', 20)
    expect(created[0].getAttribute('sandbox')).toBe('allow-scripts')
    // With `allow-same-origin` as well, the frame could reach straight back in.
    expect(created[0].getAttribute('sandbox')).not.toContain('allow-same-origin')
    await pending
    vi.restoreAllMocks()
  })

  it('assumes it fits when the frame never answers', async () => {
    // A frame that hangs must not hold the poster hostage. The person can see
    // the result for themselves, so a false alarm is worse than a missed one.
    const result = await checkFit('<html></html>', 10)
    expect(result.fits).toBe(true)
    expect(result.problems).toEqual([])
  })

  it('ignores a message from anything but its own frame', async () => {
    const result = checkFit('<html></html>', 40)
    window.postMessage(
      { source: 'pelita-fit', problems: [{ tag: 'h1', text: 'spoofed' }] },
      '*',
    )
    await new Promise((r) => setTimeout(r, 15))
    expect((await result).problems).toEqual([])
  })

  it('cleans the frame up afterwards', async () => {
    const before = document.querySelectorAll('iframe').length
    await checkFit('<html></html>', 10)
    expect(document.querySelectorAll('iframe').length).toBe(before)
  })
})

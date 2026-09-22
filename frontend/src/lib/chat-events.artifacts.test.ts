import { describe, expect, it, vi } from 'vitest'
import { dispatchFrame, type StreamHandlers } from './chat-events'

function handlers(): StreamHandlers {
  return {
    onStart: vi.fn(),
    onGuard: vi.fn(),
    onTool: vi.fn(),
    onImages: vi.fn(),
    onSources: vi.fn(),
    onToken: vi.fn(),
    onUsage: vi.fn(),
    onArtifactStart: vi.fn(),
    onArtifactStep: vi.fn(),
    onArtifactDelta: vi.fn(),
    onArtifactPart: vi.fn(),
    onArtifactPlan: vi.fn(),
    onArtifactDesign: vi.fn(),
    onArtifactDone: vi.fn(),
    onArtifactFailed: vi.fn(),
    onSuggestions: vi.fn(),
    onError: vi.fn(),
    onDone: vi.fn(),
  }
}

describe('artifact frames', () => {
  it('routes a build from start to finish', () => {
    const h = handlers()
    dispatchFrame({ event: 'artifact.start', data: '{"kind":"poster","title":"Jazz"}' }, h)
    dispatchFrame({ event: 'artifact.step', data: '{"label":"Composing","detail":""}' }, h)
    dispatchFrame({ event: 'artifact.delta', data: '{"text":"<div>"}' }, h)
    dispatchFrame({ event: 'artifact.done', data: '{"id":"a1","version":1}' }, h)

    expect(h.onArtifactStart).toHaveBeenCalledWith({ kind: 'poster', title: 'Jazz' })
    expect(h.onArtifactStep).toHaveBeenCalledWith({ label: 'Composing', detail: '' })
    expect(h.onArtifactDelta).toHaveBeenCalledWith('<div>')
    // `id`, not `artifact_id`: the card and the panel look it up by the same
    // key the REST shape uses, and a second name for it opens nothing.
    expect(h.onArtifactDone).toHaveBeenCalledWith({ id: 'a1', version: 1 })
  })

  it('keeps pieces in order however they land', async () => {
    // Slides are written several at a time and finish out of sequence. A deck
    // that appears out of order is worse than one that appears slowly.
    const { mergePart } = await import('./chat-events')
    const part = (index: number) => ({ index, total: 3, title: `s${index}`, html: '' })

    let parts = mergePart([], part(2))
    parts = mergePart(parts, part(1))
    parts = mergePart(parts, part(3))

    expect(parts.map((p) => p.index)).toEqual([1, 2, 3])
  })

  it('replaces a piece rather than duplicating it', async () => {
    const { mergePart } = await import('./chat-events')
    const first = { index: 1, total: 2, title: 'draft', html: 'a' }
    const again = { index: 1, total: 2, title: 'final', html: 'b' }
    expect(mergePart([first], again)).toEqual([again])
  })

  it('routes a failure', () => {
    const h = handlers()
    dispatchFrame(
      { event: 'artifact.failed', data: '{"message":"The design model is down.","retryable":true}' },
      h,
    )
    expect(h.onArtifactFailed).toHaveBeenCalledWith({
      message: 'The design model is down.',
      retryable: true,
    })
  })

  it('ignores an event it does not know, which is what keeps the protocol additive', () => {
    const h = handlers()
    dispatchFrame({ event: 'artifact.invented', data: '{}' }, h)
    expect(Object.values(h).every((fn) => (fn as ReturnType<typeof vi.fn>).mock.calls.length === 0)).toBe(true)
  })
})

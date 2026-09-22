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

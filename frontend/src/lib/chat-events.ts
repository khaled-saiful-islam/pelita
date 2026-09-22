/**
 * Turning SSE frames into calls.
 *
 * The wire format stops here. The hook says what each event *means* for the
 * conversation; this module knows only what arrived and how to read it — which
 * is why adding an event is one case here and one handler there, rather than
 * another branch in a function that also owns state.
 */

import type { SseMessage } from './sse'
import type {
  Artifact,
  GuardAlert,
  ImageResult,
  Source,
  StartPayload,
  ToolActivity,
  UsagePayload,
} from './chat-types'

export interface StreamHandlers {
  onStart: (start: StartPayload) => void
  onGuard: (alert: GuardAlert) => void
  onTool: (activity: ToolActivity) => void
  onImages: (images: ImageResult[]) => void
  onSources: (sources: Source[]) => void
  onToken: (text: string) => void
  onUsage: (usage: UsagePayload) => void
  onArtifactStart: (start: { kind: string; title: string }) => void
  onArtifactStep: (step: { label: string; detail: string }) => void
  onArtifactDelta: (text: string) => void
  onArtifactDone: (artifact: Artifact & { findings: string[] }) => void
  onArtifactFailed: (failure: { message: string; retryable: boolean }) => void
  onSuggestions: (items: string[]) => void
  onError: (message: string) => void
  onDone: (finishReason: string) => void
}

/** Route one frame. Unknown events are ignored, which is what makes the
 *  protocol additive — an older client simply skips what it does not know. */
export function dispatchFrame(frame: SseMessage, handlers: StreamHandlers): void {
  const payload = safeParse(frame.data)
  if (!payload) return

  switch (frame.event) {
    case 'start':
      return handlers.onStart(payload as unknown as StartPayload)
    case 'guard':
      return handlers.onGuard(payload as unknown as GuardAlert)
    case 'tool':
      return handlers.onTool(payload as unknown as ToolActivity)
    case 'images':
      return handlers.onImages((payload.images ?? []) as ImageResult[])
    case 'sources':
      return handlers.onSources((payload.sources ?? []) as Source[])
    case 'token':
      return handlers.onToken(String(payload.text ?? ''))
    case 'usage':
      return handlers.onUsage(payload as unknown as UsagePayload)
    case 'artifact.start':
      return handlers.onArtifactStart(
        payload as unknown as { kind: string; title: string },
      )
    case 'artifact.step':
      return handlers.onArtifactStep(
        payload as unknown as { label: string; detail: string },
      )
    case 'artifact.delta':
      return handlers.onArtifactDelta(String(payload.text ?? ''))
    case 'artifact.done':
      return handlers.onArtifactDone(
        payload as unknown as Artifact & { findings: string[] },
      )
    case 'artifact.failed':
      return handlers.onArtifactFailed(
        payload as unknown as { message: string; retryable: boolean },
      )
    case 'suggestions':
      return handlers.onSuggestions((payload.items ?? []) as string[])
    case 'error':
      return handlers.onError(String(payload.message ?? 'Something went wrong.'))
    case 'done':
      return handlers.onDone(String(payload.finish_reason ?? 'stop'))
  }
}

/** Replace the activity for the same tool, so running becomes done in place. */
export function mergeTool(
  existing: ToolActivity[] | undefined,
  next: ToolActivity,
): ToolActivity[] {
  const list = existing ?? []
  // A tool that is still running is updated in place; a finished one stays and
  // the next run is its own chip. Two searches in a turn are two things that
  // happened, and collapsing them hides the second one's results entirely.
  const index = list.findIndex(
    (activity) => activity.tool === next.tool && activity.status === 'running',
  )
  if (index === -1) return [...list, next]
  return list.map((activity, i) => (i === index ? next : activity))
}

/**
 * Sources from every round of a turn, in citation order.
 *
 * Appended rather than replaced: the model may search more than once, the
 * server numbers the second batch after the first, and replacing left `[3]`
 * pointing at nothing while `[8]` pointed at a list of five.
 */
export function mergeSources(
  existing: Source[] | undefined,
  next: Source[],
): Source[] {
  const byRank = new Map((existing ?? []).map((source) => [source.rank, source]))
  for (const source of next) byRank.set(source.rank, source)
  return [...byRank.values()].sort((a, b) => a.rank - b.rank)
}

/** Add this turn's usage to the conversation running total. */
export function addUsage(current: import('./chat-types').Totals | null, next: UsagePayload) {
  return {
    prompt_tokens: (current?.prompt_tokens ?? 0) + next.prompt_tokens,
    completion_tokens: (current?.completion_tokens ?? 0) + next.completion_tokens,
    total_tokens: (current?.total_tokens ?? 0) + next.total_tokens,
    cost: Number(current?.cost ?? 0) + next.cost,
    currency: next.currency,
    estimated: (current?.estimated ?? false) || next.source === 'estimated',
  }
}

function safeParse(data: string): Record<string, unknown> | null {
  try {
    return JSON.parse(data) as Record<string, unknown>
  } catch {
    return null
  }
}

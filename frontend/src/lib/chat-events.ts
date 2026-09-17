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
  const index = list.findIndex((activity) => activity.tool === next.tool)
  if (index === -1) return [...list, next]
  return list.map((activity, i) => (i === index ? next : activity))
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

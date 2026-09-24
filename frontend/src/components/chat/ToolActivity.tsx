import { AlertCircle, Check, Globe, Sparkles } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ToolActivity as Activity } from '@/hooks/useChat'

/**
 * What the assistant is doing before it starts writing.
 *
 * A search adds a few seconds before the first token. Without this the app
 * looks stalled; with it, the wait is explained and the answer arrives with
 * visible provenance.
 */
export function ToolActivityList({ activities }: { activities: Activity[] }) {
  if (activities.length === 0) return null

  return (
    <div className="mb-3 space-y-1.5">
      {activities.map((activity) => (
        <Row key={activity.tool} activity={activity} />
      ))}
    </div>
  )
}

/** The tools that make something rather than look something up. */
const MAKERS = new Set(['create_artifact', 'edit_artifact'])

function Row({ activity }: { activity: Activity }) {
  const running = activity.status === 'running'
  const failed = activity.status === 'failed'

  return (
    <div
      className={cn(
        'inline-flex items-center gap-2 rounded-lg border border-border bg-surface px-2.5 py-1.5 text-xs',
        failed && 'border-destructive/30 text-destructive',
      )}
      role="status"
      aria-live="polite"
    >
      {failed ? (
        <AlertCircle className="size-3.5 shrink-0" aria-hidden />
      ) : running ? (
        // The globe means searching. A build is not a search, and showing one
        // while a website is made said the wrong thing twice over.
        MAKERS.has(activity.tool) ? (
          <Sparkles className="size-3.5 shrink-0 animate-pulse text-primary" aria-hidden />
        ) : (
          <Globe className="size-3.5 shrink-0 animate-pulse text-primary" aria-hidden />
        )
      ) : (
        <Check className="size-3.5 shrink-0 text-success" aria-hidden />
      )}

      <span className={cn(running && 'shimmer', !running && !failed && 'text-muted-foreground')}>
        {activity.label}
      </span>

      {activity.detail && !running && (
        <span className="text-muted-foreground">· {activity.detail}</span>
      )}
    </div>
  )
}

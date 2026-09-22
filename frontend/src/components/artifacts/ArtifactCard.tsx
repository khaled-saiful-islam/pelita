import { Image as ImageIcon, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { Artifact, ArtifactBuild } from '@/lib/chat-types'

/**
 * The artifact in the transcript.
 *
 * A card, never the document: a poster in a chat bubble is four hundred lines
 * of CSS nobody asked for, and the panel is where it belongs.
 */
export function ArtifactCard({
  artifact,
  build,
  active,
  onOpen,
}: {
  artifact?: Artifact
  build?: ArtifactBuild | null
  active?: boolean
  onOpen: () => void
}) {
  const busy = !!build && !artifact
  const title = artifact?.title ?? build?.title ?? 'Artifact'
  const kind = artifact?.kind ?? build?.kind ?? 'artifact'
  const step = build?.steps[build.steps.length - 1]

  return (
    <button
      type="button"
      onClick={onOpen}
      disabled={busy}
      aria-label={busy ? `${title}, being made` : `Open ${title}`}
      className={cn(
        'mb-3 flex w-full max-w-sm items-center gap-3 rounded-lg border border-border bg-surface px-3 py-2.5 text-left transition-colors',
        !busy && 'hover:border-primary/40',
        active && 'border-primary/60',
      )}
    >
      <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-muted">
        {busy ? (
          <Loader2 className="size-4 animate-spin text-primary" aria-hidden />
        ) : (
          <ImageIcon className="size-4 text-muted-foreground" aria-hidden />
        )}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium">{title}</span>
        <span className="block truncate text-xs text-muted-foreground">
          {busy ? (step?.label ?? 'Starting') : `${kind}${artifact ? ` · v${artifact.version}` : ''}`}
        </span>
      </span>
    </button>
  )
}

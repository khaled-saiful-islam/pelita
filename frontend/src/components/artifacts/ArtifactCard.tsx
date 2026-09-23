import { AlertCircle, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { lookOf } from '@/components/artifacts/kind-look'
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
  const failed = !!build?.failed
  const busy = !!build && !artifact && !failed
  const title = artifact?.title ?? build?.title ?? 'Artifact'
  const kind = artifact?.kind ?? build?.kind ?? 'artifact'
  const step = build?.steps[build.steps.length - 1]
  const look = lookOf(kind)
  const Glyph = look.icon

  return (
    <button
      type="button"
      onClick={onOpen}
      disabled={busy}
      aria-label={busy ? `${title}, being made` : `Open ${title}`}
      className={cn(
        'mb-3 flex w-full max-w-sm items-center gap-3 rounded-xl border px-3 py-2.5 text-left transition-colors',
        // The card wears its kind, not just its icon. Three artifacts in one
        // conversation should be tellable apart across the room.
        failed
          ? 'border-destructive/40 bg-destructive/5'
          : cn(look.surface, look.border, !busy && look.hover),
        active && 'ring-2 ring-offset-1 ring-offset-background',
        active && !failed && look.ring,
      )}
    >
      <span
        className={cn(
          'flex size-9 shrink-0 items-center justify-center rounded-lg shadow-sm',
          failed ? 'bg-destructive/10' : look.tile,
        )}
      >
        {busy ? (
          <Loader2 className="size-4 animate-spin" aria-hidden />
        ) : failed ? (
          <AlertCircle className="size-4 text-destructive" aria-hidden />
        ) : (
          <Glyph className="size-4" aria-hidden />
        )}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium">{title}</span>
        <span
          className={cn(
            'block truncate text-xs',
            failed ? 'text-destructive' : 'text-muted-foreground',
          )}
        >
          {failed
            ? `Could not finish — the ${kind === 'artifact' ? 'artifact' : kind} is unchanged`
            : busy
              ? (step?.label ?? 'Starting')
              : null}
          {!failed && !busy && (
            <>
              <span className={cn('font-medium', look.colour)}>{kind}</span>
              {artifact && <span className="text-muted-foreground"> · v{artifact.version}</span>}
            </>
          )}
        </span>
      </span>
    </button>
  )
}

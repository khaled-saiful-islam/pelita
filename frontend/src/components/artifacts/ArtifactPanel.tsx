import { useState } from 'react'
import { AlertTriangle, Code2, Eye, Loader2, SquareArrowOutUpRight, X } from 'lucide-react'
import { Alert, Button } from '@/components/ui'
import { BuildSteps } from '@/components/artifacts/BuildSteps'
import { ArtifactFrame } from '@/components/artifacts/ArtifactFrame'
import { useArtifact } from '@/hooks/useArtifact'
import type { ArtifactBuild } from '@/lib/chat-types'

/**
 * The panel beside the conversation.
 *
 * It shows one of three things, and never two at once: a build in progress, a
 * finished artifact, or what went wrong. The finished artifact is not shown
 * until it has been measured — a poster that turns out to be cut off is worse
 * for having been displayed first.
 */
export function ArtifactPanel({
  artifactId,
  build,
  onClose,
}: {
  artifactId: string | null
  build?: ArtifactBuild | null
  onClose: () => void
}) {
  const { artifact, fit, error, loading } = useArtifact(artifactId)
  const [showing, setShowing] = useState<'preview' | 'source'>('preview')

  const building = !artifactId && !!build
  const measuring = !!artifact && fit === null
  const title = artifact?.title ?? build?.title ?? 'Artifact'

  return (
    <aside
      className="flex w-full shrink-0 flex-col border-l border-border bg-background md:w-[min(46vw,720px)]"
      aria-label="Artifact"
    >
      <header className="flex h-12 shrink-0 items-center justify-between gap-2 border-b border-border px-2 sm:px-3">
        <h2 className="min-w-0 truncate text-sm font-medium">{title}</h2>
        <div className="flex shrink-0 items-center gap-1">
          {artifact && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowing(showing === 'preview' ? 'source' : 'preview')}
              title={showing === 'preview' ? 'View the source' : 'View the poster'}
            >
              {showing === 'preview' ? (
                <Code2 className="size-4" aria-hidden />
              ) : (
                <Eye className="size-4" aria-hidden />
              )}
            </Button>
          )}
          {artifact && (
            <a
              href={`/api/artifacts/${artifact.id}/raw`}
              target="_blank"
              rel="noreferrer noopener"
              title="Open in a new tab"
            >
              <Button variant="ghost" size="sm">
                <SquareArrowOutUpRight className="size-4" aria-hidden />
              </Button>
            </a>
          )}
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close the panel">
            <X className="size-4" aria-hidden />
          </Button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1 flex-col">
        {building && (
          <div className="flex flex-1 flex-col gap-4 overflow-auto p-4">
            <BuildSteps build={build} />
            {build.source && (
              <pre className="min-h-0 flex-1 overflow-auto rounded-md bg-surface p-3 text-[11px] leading-relaxed text-muted-foreground">
                <code>{tail(build.source)}</code>
              </pre>
            )}
          </div>
        )}

        {build?.failed && <Alert className="m-4">{build.failed}</Alert>}
        {error && <Alert className="m-4">{error}</Alert>}

        {(loading || measuring) && !building && (
          <div className="flex flex-1 items-center justify-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" aria-hidden />
            {measuring ? 'Checking it fits' : 'Loading'}
          </div>
        )}

        {artifact && !measuring && showing === 'preview' && (
          <>
            {fit && !fit.fits && (
              <div
                className="mx-4 mt-4 flex items-start gap-2 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-xs"
                role="status"
              >
                <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warning" aria-hidden />
                <span>
                  Some text does not fit inside the poster
                  {fit.problems[0]?.text ? ` — "${fit.problems[0].text}"` : ''}. Ask for it to be
                  fixed and it will be redrawn.
                </span>
              </div>
            )}
            <ArtifactFrame
              html={artifact.html}
              width={artifact.width}
              height={artifact.height}
              sandbox={artifact.sandbox}
              title={artifact.title}
            />
          </>
        )}

        {artifact && !measuring && showing === 'source' && (
          <pre className="flex-1 overflow-auto p-4 text-[11px] leading-relaxed">
            <code>{artifact.html}</code>
          </pre>
        )}
      </div>
    </aside>
  )
}

/** The last of a document being written. Keeping the whole thing on screen
 *  means the interesting end is always off the bottom. */
function tail(source: string, lines = 40): string {
  const all = source.split('\n')
  return all.slice(Math.max(0, all.length - lines)).join('\n')
}

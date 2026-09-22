import { useState } from 'react'
import {
  AlertTriangle,
  Check,
  Code2,
  Download,
  Eye,
  Link2,
  Loader2,
  Pencil,
  SquareArrowOutUpRight,
  Wand2,
  X,
} from 'lucide-react'
import { Alert, Button } from '@/components/ui'
import { BuildSteps } from '@/components/artifacts/BuildSteps'
import { ArtifactFrame } from '@/components/artifacts/ArtifactFrame'
import { EditableFrame } from '@/components/artifacts/EditableFrame'
import { ShareArtifactDialog } from '@/components/artifacts/ShareArtifactDialog'
import { useArtifact } from '@/hooks/useArtifact'
import { apiFetch } from '@/lib/api'
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
  const { artifact, fit, error, loading, reload } = useArtifact(artifactId)
  const [showing, setShowing] = useState<'preview' | 'source'>('preview')
  const [sharing, setSharing] = useState(false)
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  // Collected rather than sent per keystroke: one version per edit, not one
  // per letter.
  const [changes, setChanges] = useState<Map<number, string>>(new Map())
  const [instruction, setInstruction] = useState('')
  const [revising, setRevising] = useState(false)
  const [revisionError, setRevisionError] = useState<string | null>(null)

  async function revise(event: React.FormEvent) {
    event.preventDefault()
    if (!artifact || !instruction.trim() || revising) return
    setRevising(true)
    setRevisionError(null)
    try {
      await apiFetch(`/artifacts/${artifact.id}/revise`, {
        method: 'POST',
        body: JSON.stringify({ instruction: instruction.trim() }),
      })
      setInstruction('')
      await reload(artifact.id)
    } catch (cause) {
      // The poster they are looking at is untouched, so this is a message and
      // not a broken panel.
      setRevisionError((cause as Error).message)
    } finally {
      setRevising(false)
    }
  }

  async function saveText() {
    if (!artifact || changes.size === 0) {
      setEditing(false)
      return
    }
    setSaving(true)
    try {
      await apiFetch(`/artifacts/${artifact.id}/text`, {
        method: 'POST',
        body: JSON.stringify({
          changes: [...changes].map(([index, text]) => ({ index, text })),
        }),
      })
      setChanges(new Map())
      setEditing(false)
      await reload(artifact.id)
    } finally {
      setSaving(false)
    }
  }

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
          {artifact && artifact.versions.length > 1 && (
            <select
              aria-label="Version"
              className="rounded-md border border-border bg-surface px-2 py-1 text-xs"
              value={artifact.version}
              onChange={(event) => {
                void reload(artifact.id, Number(event.target.value))
              }}
            >
              {artifact.versions.map((v) => (
                <option key={v.version} value={v.version}>
                  v{v.version}
                </option>
              ))}
            </select>
          )}
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
          {artifact && showing === 'preview' && (
            <Button
              variant={editing ? 'primary' : 'ghost'}
              size="sm"
              disabled={saving}
              onClick={() => (editing ? void saveText() : setEditing(true))}
              title={editing ? 'Save the words' : 'Edit the words in place'}
            >
              {editing ? (
                <>
                  <Check className="size-4" aria-hidden />
                  <span className="hidden sm:inline">
                    {changes.size ? `Save ${changes.size}` : 'Done'}
                  </span>
                </>
              ) : (
                <Pencil className="size-4" aria-hidden />
              )}
            </Button>
          )}
          {artifact && !editing && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setSharing(true)}
              title="Share a public link"
            >
              <Link2 className="size-4" aria-hidden />
            </Button>
          )}
          {artifact && !editing && (
            // A plain link, not fetch-and-blob: the browser already knows how
            // to save a file the server marked as an attachment.
            <a
              href={`/api/artifacts/${artifact.id}/download?version=${artifact.version}`}
              download
              title="Download the file"
            >
              <Button variant="ghost" size="sm">
                <Download className="size-4" aria-hidden />
              </Button>
            </a>
          )}
          {artifact && !editing && (
            <a
              href={`/api/artifacts/${artifact.id}/raw?version=${artifact.version}`}
              target="_blank"
              rel="noreferrer noopener"
              title="Open in a new tab, where it can also be printed"
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

        {artifact && !measuring && showing === 'preview' && editing && (
          <>
            <p className="mx-4 mt-4 rounded-md bg-surface px-3 py-2 text-xs text-muted-foreground">
              Click any words on the poster to change them. Only the words change — nothing else
              about the design moves.
            </p>
            <EditableFrame
              html={artifact.html}
              width={artifact.width}
              height={artifact.height}
              title={artifact.title}
              onChange={(index, text) =>
                setChanges((current) => new Map(current).set(index, text))
              }
            />
          </>
        )}

        {artifact && !measuring && showing === 'preview' && !editing && (
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

      {artifact && !editing && showing === 'preview' && (
        <form onSubmit={revise} className="shrink-0 border-t border-border p-3">
          {revisionError && <Alert className="mb-2">{revisionError}</Alert>}
          <div className="flex items-center gap-2">
            <input
              value={instruction}
              onChange={(event) => setInstruction(event.target.value)}
              disabled={revising}
              placeholder="Ask for a change — warmer colours, bigger date…"
              aria-label="Ask for a change to the design"
              className="min-w-0 flex-1 rounded-md border border-border bg-surface px-3 py-2 text-sm outline-none focus:border-primary"
            />
            <Button type="submit" size="sm" disabled={revising || !instruction.trim()}>
              {revising ? (
                <Loader2 className="size-4 animate-spin" aria-hidden />
              ) : (
                <Wand2 className="size-4" aria-hidden />
              )}
              <span className="hidden sm:inline">{revising ? 'Redrawing' : 'Change'}</span>
            </Button>
          </div>
          <p className="mt-1.5 text-xs text-muted-foreground">
            Changing words only? Use the pencil — it is instant and nothing else moves.
          </p>
        </form>
      )}

      {sharing && artifact && (
        <ShareArtifactDialog
          artifactId={artifact.id}
          version={artifact.version}
          onClose={() => setSharing(false)}
        />
      )}
    </aside>
  )
}

/** The last of a document being written. Keeping the whole thing on screen
 *  means the interesting end is always off the bottom. */
function tail(source: string, lines = 40): string {
  const all = source.split('\n')
  return all.slice(Math.max(0, all.length - lines)).join('\n')
}

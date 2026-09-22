import { useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle,
  Check,
  ChevronLeft,
  ChevronRight,
  Code2,
  Download,
  Image as ImageIcon,
  Link2,
  Loader2,
  Pencil,
  SquareArrowOutUpRight,
  X,
} from 'lucide-react'
import { Alert, Button } from '@/components/ui'
import { BuildSteps } from '@/components/artifacts/BuildSteps'
import { ArtifactFrame } from '@/components/artifacts/ArtifactFrame'
import { DeckFrame } from '@/components/artifacts/DeckFrame'
import { DeckFilmstrip } from '@/components/artifacts/DeckFilmstrip'
import { DeckBuilding } from '@/components/artifacts/DeckBuilding'
import { EditableFrame } from '@/components/artifacts/EditableFrame'
import { ShareArtifactDialog } from '@/components/artifacts/ShareArtifactDialog'
import { useArtifact } from '@/hooks/useArtifact'
import { apiFetch } from '@/lib/api'
import { cn } from '@/lib/utils'
import { isDeck, slidesOf } from '@/lib/deck'
import type { ArtifactBuild } from '@/lib/chat-types'

/**
 * The panel beside the conversation.
 *
 * It shows one of three things and never two at once: a build in progress, a
 * finished artifact, or what went wrong.
 *
 * The artifact appears as soon as it has loaded. It is measured alongside
 * rather than beforehand — waiting on fonts inside a throwaway frame takes
 * seconds, and a panel showing nothing for five of them is a worse failure,
 * and a far more common one, than the clipping it was waiting to rule out.
 */
export function ArtifactPanel({
  artifactId,
  revision,
  build,
  onClose,
}: {
  artifactId: string | null
  /** Bumped whenever a turn finishes changing this artifact, so the panel
   *  reloads it — the id stays the same across an edit. */
  revision?: number
  build?: ArtifactBuild | null
  onClose: () => void
}) {
  const { artifact, fit, error, loading, reload } = useArtifact(artifactId, revision)
  const [showing, setShowing] = useState<'preview' | 'source'>('preview')
  const [sharing, setSharing] = useState(false)
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  // Collected rather than sent per keystroke: one save, not one per letter.
  const [changes, setChanges] = useState<Map<number, string>>(new Map())

  const building = !artifactId && !!build
  const title = artifact?.title ?? build?.title ?? 'Artifact'

  const deck = !!artifact && isDeck(artifact.kind, artifact.html)
  const slides = useMemo(
    () => (artifact && deck ? slidesOf(artifact.html) : []),
    [artifact, deck],
  )
  const [current, setCurrent] = useState(0)

  // Back to the first slide whenever a different deck, or a different version
  // of one, arrives — slide nine of the old one is not slide nine of this one.
  useEffect(() => setCurrent(0), [artifact?.id, artifact?.version])

  useEffect(() => {
    if (!deck || slides.length < 2 || editing) return
    const onKey = (event: KeyboardEvent) => {
      // Not while somebody is typing into the chat box.
      const typing = document.activeElement
      if (typing instanceof HTMLTextAreaElement || typing instanceof HTMLInputElement) return
      if (event.key === 'ArrowRight' || event.key === 'PageDown') {
        setCurrent((n) => Math.min(n + 1, slides.length - 1))
      } else if (event.key === 'ArrowLeft' || event.key === 'PageUp') {
        setCurrent((n) => Math.max(n - 1, 0))
      } else if (event.key === 'Home') {
        setCurrent(0)
      } else if (event.key === 'End') {
        setCurrent(slides.length - 1)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [deck, slides.length, editing])

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

  return (
    <div className="flex min-w-0 flex-1 flex-col bg-surface">
      <header className="flex h-12 shrink-0 items-center gap-2 border-b border-border bg-background px-2 sm:px-3">
        <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-muted">
          <ImageIcon className="size-3.5 text-muted-foreground" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-sm font-medium leading-tight">{title}</h2>
          {artifact && (
            <p className="truncate text-[11px] leading-tight text-muted-foreground">
              {artifact.kind} · {artifact.width}×{artifact.height}
              {artifact.versions.length > 1 && ` · v${artifact.version}`}
            </p>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-0.5">
          {artifact && !editing && (
            <div className="mr-1 flex rounded-md bg-muted p-0.5">
              <Tab active={showing === 'preview'} onClick={() => setShowing('preview')}>
                <ImageIcon className="size-3.5" aria-hidden />
                <span className="hidden lg:inline">Preview</span>
              </Tab>
              <Tab active={showing === 'source'} onClick={() => setShowing('source')}>
                <Code2 className="size-3.5" aria-hidden />
                <span className="hidden lg:inline">Code</span>
              </Tab>
            </div>
          )}

          {artifact && artifact.versions.length > 1 && !editing && (
            <select
              aria-label="Version"
              className="mr-1 rounded-md border border-border bg-background px-1.5 py-1 text-xs"
              value={artifact.version}
              onChange={(event) => void reload(artifact.id, Number(event.target.value))}
            >
              {artifact.versions.map((v) => (
                <option key={v.version} value={v.version}>
                  v{v.version}
                </option>
              ))}
            </select>
          )}

          {artifact && showing === 'preview' && (
            <Button
              variant={editing ? 'primary' : 'ghost'}
              size="sm"
              disabled={saving}
              onClick={() => (editing ? void saveText() : setEditing(true))}
              title={editing ? 'Save the words' : 'Edit the words in place'}
            >
              {saving ? (
                <Loader2 className="size-4 animate-spin" aria-hidden />
              ) : editing ? (
                <Check className="size-4" aria-hidden />
              ) : (
                <Pencil className="size-4" aria-hidden />
              )}
              {editing && (
                <span className="hidden sm:inline">
                  {changes.size ? `Save ${changes.size}` : 'Done'}
                </span>
              )}
            </Button>
          )}

          {artifact && !editing && (
            <>
              <Button variant="ghost" size="sm" onClick={() => setSharing(true)} title="Share a link">
                <Link2 className="size-4" aria-hidden />
              </Button>
              <DownloadMenu artifact={artifact} />
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
            </>
          )}

          <span className="mx-1 h-5 w-px bg-border" aria-hidden />
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close the panel">
            <X className="size-4" aria-hidden />
          </Button>
        </div>
      </header>

      <div className="relative flex min-h-0 flex-1 flex-col">
        {building && (
          <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-auto p-5">
            <BuildSteps build={build} />
            {(build.plan?.length || build.parts.length > 0) && <DeckBuilding build={build} />}
            {build.source && !build.plan?.length && (
              <pre className="min-h-0 flex-1 overflow-auto rounded-lg border border-border bg-background p-3 text-[11px] leading-relaxed text-muted-foreground">
                <code>{tail(build.source)}</code>
              </pre>
            )}
          </div>
        )}

        {build?.failed && <Alert className="m-4">{build.failed}</Alert>}
        {error && <Alert className="m-4">{error}</Alert>}

        {loading && !building && (
          <div className="flex flex-1 items-center justify-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" aria-hidden /> Loading
          </div>
        )}

        {artifact && showing === 'preview' && (
          <>
            {editing && (
              <p className="mx-4 mt-3 rounded-md border border-primary/30 bg-primary/5 px-3 py-2 text-xs">
                Click any words on the poster to change them. Only the words change — nothing
                else moves, and it is saved without redrawing.
              </p>
            )}
            {!editing && fit && !fit.fits && (
              <div
                className="mx-4 mt-3 flex items-start gap-2 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-xs"
                role="status"
              >
                <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warning" aria-hidden />
                <span>
                  Some text does not fit inside the poster
                  {fit.problems[0]?.text ? ` — “${fit.problems[0].text}”` : ''}. Ask for it to be
                  fixed in the chat and it will be redrawn.
                </span>
              </div>
            )}
            {deck && !editing ? (
              <>
                <DeckFrame
                  html={artifact.html}
                  width={artifact.width}
                  height={artifact.height}
                  count={slides.length}
                  current={current}
                  sandbox={artifact.sandbox}
                  title={artifact.title}
                />
                <DeckControls
                  current={current}
                  total={slides.length}
                  heading={slides[current]?.heading ?? ''}
                  onGo={setCurrent}
                />
              </>
            ) : editing ? (
              <EditableFrame
                html={artifact.html}
                width={artifact.width}
                height={artifact.height}
                title={artifact.title}
                onChange={(index, text) =>
                  setChanges((current) => new Map(current).set(index, text))
                }
              />
            ) : (
              <ArtifactFrame
                html={artifact.html}
                width={artifact.width}
                height={artifact.height}
                sandbox={artifact.sandbox}
                title={artifact.title}
              />
            )}
          </>
        )}

        {artifact && showing === 'source' && (
          <pre className="flex-1 overflow-auto bg-background p-4 text-[11px] leading-relaxed">
            <code>{artifact.html}</code>
          </pre>
        )}
      </div>

      {artifact && deck && !editing && showing === 'preview' && (
        <DeckFilmstrip
          html={artifact.html}
          slides={slides}
          width={artifact.width}
          height={artifact.height}
          current={current}
          sandbox={artifact.sandbox}
          onPick={setCurrent}
        />
      )}

      {artifact && !editing && (
        <footer className="shrink-0 border-t border-border px-4 py-2 text-[11px] text-muted-foreground">
          Ask for a change in the chat. To fix a word, use the pencil — it is instant.
        </footer>
      )}

      {sharing && artifact && (
        <ShareArtifactDialog
          artifactId={artifact.id}
          version={artifact.version}
          onClose={() => setSharing(false)}
        />
      )}
    </div>
  )
}

/**
 * Saving the poster.
 *
 * A picture by default, because that is what a poster is for — it goes into a
 * message or a feed, and neither takes an HTML file. The document is the
 * second option, for whoever wants to edit it again later.
 *
 * Plain links, not fetch-and-blob: the browser already knows how to save a
 * file the server marked as an attachment.
 */
function DownloadMenu({
  artifact,
}: {
  artifact: { id: string; version: number }
}) {
  const [open, setOpen] = useState(false)
  const base = `/api/artifacts/${artifact.id}/download?version=${artifact.version}`

  return (
    <span className="relative">
      <Button
        variant="ghost"
        size="sm"
        onClick={() => setOpen((was) => !was)}
        aria-expanded={open}
        title="Download"
      >
        <Download className="size-4" aria-hidden />
      </Button>
      {open && (
        <>
          <span className="fixed inset-0 z-10" onClick={() => setOpen(false)} aria-hidden />
          <span className="absolute right-0 top-full z-20 mt-1 flex w-44 flex-col overflow-hidden rounded-lg border border-border bg-background py-1 shadow-lg">
            <a
              href={base}
              download
              onClick={() => setOpen(false)}
              className="px-3 py-2 text-left text-xs hover:bg-muted"
            >
              <span className="block font-medium">Picture (PNG)</span>
              <span className="block text-muted-foreground">To post or send</span>
            </a>
            <a
              href={`${base}&format=html`}
              download
              onClick={() => setOpen(false)}
              className="px-3 py-2 text-left text-xs hover:bg-muted"
            >
              <span className="block font-medium">Document (HTML)</span>
              <span className="block text-muted-foreground">To edit or print later</span>
            </a>
          </span>
        </>
      )}
    </span>
  )
}

/** Where you are in the deck, and how to move. */
function DeckControls({
  current,
  total,
  heading,
  onGo,
}: {
  current: number
  total: number
  heading: string
  onGo: (index: number) => void
}) {
  if (total < 2) return null
  return (
    <div className="flex shrink-0 items-center gap-3 px-4 pb-1">
      <Button
        variant="ghost"
        size="icon"
        disabled={current === 0}
        onClick={() => onGo(current - 1)}
        aria-label="Previous slide"
      >
        <ChevronLeft className="size-4" aria-hidden />
      </Button>
      <span className="min-w-0 flex-1 truncate text-center text-xs text-muted-foreground">
        <span className="font-mono tabular-nums">
          {current + 1} / {total}
        </span>
        {heading && <span className="ml-2">{heading}</span>}
      </span>
      <Button
        variant="ghost"
        size="icon"
        disabled={current >= total - 1}
        onClick={() => onGo(current + 1)}
        aria-label="Next slide"
      >
        <ChevronRight className="size-4" aria-hidden />
      </Button>
    </div>
  )
}

function Tab({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        'flex items-center gap-1.5 rounded px-2 py-1 text-xs transition-colors',
        active
          ? 'bg-background text-foreground shadow-sm'
          : 'text-muted-foreground hover:text-foreground',
      )}
    >
      {children}
    </button>
  )
}

/** The last of a document being written. Keeping all of it on screen means the
 *  interesting end is always off the bottom. */
function tail(source: string, lines = 40): string {
  const all = source.split('\n')
  return all.slice(Math.max(0, all.length - lines)).join('\n')
}

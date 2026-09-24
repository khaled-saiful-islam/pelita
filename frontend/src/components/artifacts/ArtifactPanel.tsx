import { useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle,
  Check,
  ChevronLeft,
  ChevronRight,
  Code2,
  Image as ImageIcon,
  Link2,
  Loader2,
  Pencil,
  RotateCcw,
  SquareArrowOutUpRight,
  X,
} from 'lucide-react'
import { Alert, Button } from '@/components/ui'
import { BuildSteps } from '@/components/artifacts/BuildSteps'
import { ArtifactFrame } from '@/components/artifacts/ArtifactFrame'
import { DeckFrame } from '@/components/artifacts/DeckFrame'
import { DeckFilmstrip } from '@/components/artifacts/DeckFilmstrip'
import { ArtifactBuilding } from '@/components/artifacts/ArtifactBuilding'
import { lookOf } from '@/components/artifacts/kind-look'
import { EditableFrame } from '@/components/artifacts/EditableFrame'
import { SiteBar } from '@/components/artifacts/SiteBar'
import { SiteFrame } from '@/components/artifacts/SiteFrame'
import { ShareArtifactDialog } from '@/components/artifacts/ShareArtifactDialog'
import { DownloadMenu } from '@/components/artifacts/DownloadMenu'
import { useArtifact } from '@/hooks/useArtifact'
import { apiFetch } from '@/lib/api'
import { cn } from '@/lib/utils'
import { isDeck, slidesOf } from '@/lib/deck'
import { isApp, isFluid, isSite, sitePages, withState, type Device } from '@/lib/site'
import { useAppState } from '@/hooks/useAppState'
import { Confirm } from '@/components/ui/Confirm'
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
  const headLook = lookOf(artifact?.kind ?? build?.kind)
  const HeadGlyph = headLook.icon
  const title = artifact?.title ?? build?.title ?? 'Artifact'

  const deck = !!artifact && isDeck(artifact.kind, artifact.html)
  // Decided by the kind, because what a download should be is a
  // property of the thing: a picture of a game is its first frame with
  // nobody playing.
  const playable = artifact?.kind === 'games'
  const slides = useMemo(
    () => (artifact && deck ? slidesOf(artifact.html) : []),
    [artifact, deck],
  )
  const [current, setCurrent] = useState(0)

  const site = !!artifact && isSite(artifact.kind)
  const app = !!artifact && isApp(artifact.kind)
  const fluid = !!artifact && isFluid(artifact.kind)
  const kept = useAppState(app && artifact ? artifact.id : null)
  const [startingOver, setStartingOver] = useState(false)
  // What the app opens with: its document, with what this person saved put in
  // front of it. Recomputed for a new version or a fresh start, never for a
  // save — the frame must not reload every time somebody ticks a box.
  const appHtml = useMemo(
    () => (app && artifact && kept.ready ? withState(artifact.html, kept.current()) : null),
    [app, artifact?.html, kept.ready, kept.nonce],
  )
  const pages = useMemo(() => (artifact && site ? sitePages(artifact.html) : []), [artifact, site])
  const [device, setDevice] = useState<Device>('desktop')
  const [sitePage, setSitePage] = useState<string | null>(null)

  // Back to the first slide whenever a different deck, or a different version
  // of one, arrives — slide nine of the old one is not slide nine of this one.
  // The same for a site's page: a new version may not have the old one.
  useEffect(() => {
    setCurrent(0)
    setSitePage(null)
  }, [artifact?.id, artifact?.version])

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
        <span
          className={cn(
            'flex size-7 shrink-0 items-center justify-center rounded-md',
            headLook.tile,
          )}
        >
          <HeadGlyph className="size-3.5" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-sm font-medium leading-tight">{title}</h2>
          {artifact && (
            <p className="truncate text-[11px] leading-tight text-muted-foreground">
              {artifact.kind} ·{' '}
              {site
                ? `${pages.length} page${pages.length === 1 ? '' : 's'}`
                : app
                  ? 'remembers your data'
                  : `${artifact.width}×${artifact.height}`}
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
              <DownloadMenu artifact={artifact} deck={deck} playable={playable} site={site} app={app} />
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
            {/* The look, the plan and the finished pieces — never the source.
                Watching markup scroll past is not a preview of anything, and
                it is the one thing on screen that nobody reading it wants. */}
            <ArtifactBuilding build={build} />
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
            {fluid && (
              <SiteBar
                pages={pages}
                page={sitePage}
                onPage={setSitePage}
                device={device}
                onDevice={setDevice}
                fit={app}
                actions={
                  app && !editing ? (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setStartingOver(true)}
                      title="Clear what this app has saved and open it empty"
                    >
                      <RotateCcw className="size-3.5" aria-hidden />
                      <span className="hidden lg:inline">Start over</span>
                    </Button>
                  ) : null
                }
              />
            )}
            {app && kept.error && (
              <p className="mx-4 mt-2 text-xs text-warning" role="status">
                {kept.error}
              </p>
            )}
            {editing && (
              <p className="mx-4 mt-3 rounded-md border border-primary/30 bg-primary/5 px-3 py-2 text-xs">
                Click any words on the {site ? 'site' : 'poster'} to change them.
                {site && ' Use the pages above to reach the others.'} Only the words
                change — nothing else moves, and it is saved without redrawing.
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
            {app ? (
              appHtml ? (
                <SiteFrame
                  html={appHtml}
                  sandbox={artifact.sandbox}
                  title={artifact.title}
                  device={device}
                  fit
                  onStore={kept.save}
                  onEdit={
                    editing
                      ? (index, text) => setChanges((was) => new Map(was).set(index, text))
                      : undefined
                  }
                />
              ) : (
                <div className="flex flex-1 items-center justify-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="size-4 animate-spin" aria-hidden /> Opening
                </div>
              )
            ) : site ? (
              <SiteFrame
                html={artifact.html}
                sandbox={artifact.sandbox}
                title={artifact.title}
                device={device}
                page={sitePage}
                onPage={setSitePage}
                onEdit={
                  editing
                    ? (index, text) => setChanges((was) => new Map(was).set(index, text))
                    : undefined
                }
              />
            ) : deck && !editing ? (
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

      {startingOver && (
        <Confirm
          title="Start this app over?"
          body="Everything it has saved for you — its entries, its settings — will be cleared, and it will open empty. The app itself stays as it is."
          confirmLabel="Start over"
          onCancel={() => setStartingOver(false)}
          onConfirm={() => {
            setStartingOver(false)
            void kept.reset()
          }}
        />
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

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Download, Link2, Menu } from 'lucide-react'
import { Alert, Button } from '@/components/ui'
import { Logo } from '@/components/Logo'
import { Composer, type ComposerHandle } from '@/components/chat/Composer'
import { MakeChips } from '@/components/make/MakeChips'
import { MakeRail } from '@/components/make/MakeRail'
import { inOrder, startWith, type Makeable } from '@/components/make/showcase'
import { MessageList } from '@/components/chat/MessageList'
import { Sidebar } from '@/components/sidebar/Sidebar'
import { ConversationUsage } from '@/components/chat/Usage'
import { NewsStrip } from '@/components/news/NewsStrip'
import { AttachmentError } from '@/components/chat/AttachmentError'
import { Suggestions } from '@/components/chat/Suggestions'
import { ShareDialog } from '@/components/chat/ShareDialog'
import { ArtifactPanel } from '@/components/artifacts/ArtifactPanel'
import { PanelHandle } from '@/components/artifacts/PanelHandle'
import { usePanelWidth } from '@/hooks/usePanelWidth'
import { useChat } from '@/hooks/useChat'
import { useConversations } from '@/hooks/useConversations'
import { useConfig } from '@/hooks/useConfig'
import { useDocuments } from '@/hooks/useDocuments'
import { apiFetch } from '@/lib/api'

export default function Chat() {
  const { conversationId: routeId } = useParams<{ conversationId: string }>()
  const navigate = useNavigate()
  const list = useConversations()
  const config = useConfig()
  const [loadError, setLoadError] = useState<string | null>(null)
  const [menuOpen, setMenuOpen] = useState(false)

  const onConversationStarted = useCallback(
    (id: string, title: string) => {
      list.upsert(id, title)
      // Put the id in the URL without a navigation, so a reload or a shared
      // link lands on this conversation.
      window.history.replaceState(null, '', `/c/${id}`)
    },
    [list],
  )

  const chat = useChat(onConversationStarted)
  const { load, reset } = chat

  const activeConversationId = chat.conversationId ?? routeId ?? null
  const documents = useDocuments(activeConversationId, { images: config?.images_enabled ?? false })
  const [sharing, setSharing] = useState(false)
  const composer = useRef<ComposerHandle>(null)
  const kinds: Makeable[] = useMemo(() => inOrder(config?.makeable ?? []), [config])

  /** A kind picked from the rail or the chips: its request, ready to edit. */
  function start(kind: Makeable, example?: string) {
    const { text, selection } = startWith(kind, example)
    composer.current?.fill(text, selection)
  }

  useEffect(() => {
    setLoadError(null)
    if (!routeId) {
      reset()
      return
    }
    load(routeId).catch((error: Error) => setLoadError(error.message))
  }, [routeId, load, reset])

  function startNew() {
    reset()
    documents.reset()
    navigate('/')
    setMenuOpen(false)
  }

  /**
   * Attach a file, creating the conversation first if there is not one yet.
   *
   * A file belongs to a conversation, and someone can attach one before typing
   * anything — so the chat starts when the file does.
   */
  async function attach(file: File) {
    let target = activeConversationId
    if (!target) {
      try {
        const created = await apiFetch<{ id: string; title: string }>('/conversations', {
          method: 'POST',
        })
        target = created.id
        list.upsert(created.id, created.title)
        window.history.replaceState(null, '', `/c/${created.id}`)
        navigate(`/c/${created.id}`, { replace: true })
      } catch {
        return
      }
    }
    await documents.attach(file, target)
  }

  async function remove(id: string) {
    await list.remove(id)
    if (id === chat.conversationId || id === routeId) startNew()
  }

  const empty = chat.messages.length === 0
  // The build on the answer being written, so the panel can show it before
  // there is an artifact to show.
  const building = chat.messages[chat.messages.length - 1]?.building ?? null
  const panelOpen = !!chat.openArtifact || !!building
  const panel = usePanelWidth()

  return (
    <div className="flex h-dvh overflow-hidden">
      <Sidebar
        conversations={list.conversations}
        activeId={activeConversationId}
        loading={list.loading}
        open={menuOpen}
        onClose={() => setMenuOpen(false)}
        onSelect={(id) => {
          navigate(`/c/${id}`)
          setMenuOpen(false)
        }}
        onNew={startNew}
        onRename={list.rename}
        onDelete={remove}
      />

      <main className="flex min-w-0 flex-1 flex-col">
        {empty && (
          // The empty screen has no header of its own, so the drawer needs its
          // own way in on mobile.
          <div className="flex h-12 shrink-0 items-center px-2 md:hidden">
            <MenuButton onClick={() => setMenuOpen(true)} />
          </div>
        )}

        {!empty && (
          <header className="flex h-12 shrink-0 items-center justify-between gap-2 border-b border-border px-2 sm:gap-4 sm:px-4">
            <div className="flex min-w-0 items-center gap-1">
              <MenuButton onClick={() => setMenuOpen(true)} className="md:hidden" />
              <h1 className="truncate text-sm font-medium">{chat.title}</h1>
            </div>
            <div className="flex shrink-0 items-center gap-3">
              {chat.totals && <ConversationUsage totals={chat.totals} />}
            {activeConversationId && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setSharing(true)}
                title="Share a public link"
              >
                <Link2 className="size-4" aria-hidden />
                <span className="hidden sm:inline">Share</span>
              </Button>
            )}
            {activeConversationId && (
              // A plain link, not fetch-and-blob: the browser already knows how
              // to save a file the server marked as an attachment.
              <a
                href={`/api/conversations/${activeConversationId}/export`}
                download
                className="shrink-0"
                title="Export as Markdown"
              >
                <Button variant="ghost" size="sm">
                  <Download className="size-4" aria-hidden />
                  <span className="hidden sm:inline">Export</span>
                </Button>
              </a>
            )}
            </div>
          </header>
        )}

        {empty ? (
          <>
            {/* The news leads now, at the top, and what can be made sits
                where the decision is — right above the box. */}
            <div className="pt-3">
              <NewsStrip
                onAsk={(headline, source) =>
                  // Written into the box, not sent: they may want to ask
                  // something narrower than "tell me more".
                  composer.current?.fill(`Tell me more about this story from ${source}: "${headline}"`)
                }
              />
            </div>
            <EmptyState canMake={kinds.length > 0} />
          </>
        ) : (
          <MessageList
            messages={chat.messages}
            ratings={chat.ratings}
            currency={chat.currency}
            onRate={chat.rate}
            onRegenerate={chat.regenerate}
            openArtifact={chat.openArtifact}
            onOpenArtifact={chat.setOpenArtifact}
            footer={
              <Suggestions
                items={chat.suggestions}
                disabled={chat.streaming}
                onPick={(text) => void chat.send(text)}
              />
            }
          />
        )}

        {(loadError || chat.error) && (
          <div className="mx-auto w-full max-w-[var(--message-column)] px-4">
            <Alert>{loadError ?? chat.error}</Alert>
          </div>
        )}

        {documents.error && (
          <AttachmentError message={documents.error} onDismiss={documents.clearError} />
        )}

        <Composer
          ref={composer}
          above={
            kinds.length === 0 ? null : empty ? (
              <MakeRail kinds={kinds} onPick={start} />
            ) : (
              <MakeChips kinds={kinds} hidden={chat.streaming} onPick={(kind) => start(kind)} />
            )
          }
          onSend={(text, options) =>
            chat.send(text, {
              searchMode: options.searchMode,
              // What is on screen, so "make it warmer" has a subject.
              artifactId: chat.openArtifact,
              // The pending files become cards on this message, and leave the
              // composer — the server binds them to the same id.
              documents: documents.pending,
              onSent: documents.markSent,
            })
          }
          onStop={chat.stop}
          streaming={chat.streaming}
          searchEnabled={config?.search_enabled ?? false}
          imagesEnabled={config?.images_enabled ?? false}
          files={documents.pending}
          uploadingFile={documents.uploading}
          atFileLimit={documents.files.length >= documents.maxFiles}
          onAttach={attach}
          onRemoveFile={(id) => {
            if (activeConversationId) void documents.remove(id, activeConversationId)
          }}
          autoFocus
        />
      </main>

      {panelOpen && (
        <>
          <PanelHandle
            dragging={panel.dragging}
            onStart={panel.startDragging}
            onReset={panel.reset}
          />
          <div
            className="flex shrink-0 border-l border-border"
            style={{ width: panel.width }}
          >
            <ArtifactPanel
              artifactId={chat.openArtifact}
              revision={chat.artifactRevision}
              build={building}
              onClose={() => chat.setOpenArtifact(null)}
            />
          </div>
        </>
      )}

      {sharing && activeConversationId && (
        <ShareDialog
          conversationId={activeConversationId}
          messageCount={chat.messages.length}
          onClose={() => setSharing(false)}
        />
      )}
    </div>
  )
}

function MenuButton({ onClick, className }: { onClick: () => void; className?: string }) {
  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={onClick}
      aria-label="Open menu"
      className={className}
    >
      <Menu className="size-4" aria-hidden />
    </Button>
  )
}

function EmptyState({ canMake }: { canMake: boolean }) {
  return (
    <div className="flex flex-1 items-center justify-center px-4 py-6">
      <div className="flex flex-col items-center text-center">
        <Logo className="size-10" />
        <h1 className="mt-4 text-2xl font-semibold tracking-tight">How can I help?</h1>
        <p className="mt-2 max-w-sm text-sm text-muted-foreground">
          {canMake
            ? 'Ask anything, or make something — a poster, a deck, a game, a website, an app.'
            : 'Ask anything. Pelita replies in the language you write in.'}
        </p>
      </div>
    </div>
  )
}

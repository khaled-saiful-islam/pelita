import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Download, Menu } from 'lucide-react'
import { Alert, Button } from '@/components/ui'
import { Logo } from '@/components/Logo'
import { Composer } from '@/components/chat/Composer'
import { MessageList } from '@/components/chat/MessageList'
import { Sidebar } from '@/components/sidebar/Sidebar'
import { ConversationUsage } from '@/components/chat/Usage'
import { NewsStrip } from '@/components/news/NewsStrip'
import { AttachmentError } from '@/components/chat/AttachmentError'
import { Suggestions } from '@/components/chat/Suggestions'
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
  const documents = useDocuments(activeConversationId)

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
          <EmptyState />
        ) : (
          <MessageList
            messages={chat.messages}
            ratings={chat.ratings}
            currency={chat.currency}
            onRate={chat.rate}
            onRegenerate={chat.regenerate}
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

        {empty && <NewsStrip />}

        {documents.error && (
          <AttachmentError message={documents.error} onDismiss={documents.clearError} />
        )}

        <Composer
          onSend={(text, options) =>
            chat.send(text, {
              searchMode: options.searchMode,
              // The pending files become cards on this message, and leave the
              // composer — the server binds them to the same id.
              documents: documents.pending,
              onSent: documents.markSent,
            })
          }
          onStop={chat.stop}
          streaming={chat.streaming}
          searchEnabled={config?.search_enabled ?? false}
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

function EmptyState() {
  return (
    <div className="flex flex-1 items-center justify-center px-4">
      <div className="flex flex-col items-center text-center">
        <Logo className="size-10" />
        <h1 className="mt-4 text-2xl font-semibold tracking-tight">How can I help?</h1>
        <p className="mt-2 max-w-sm text-sm text-muted-foreground">
          Ask anything. Pelita replies in the language you write in.
        </p>
      </div>
    </div>
  )
}

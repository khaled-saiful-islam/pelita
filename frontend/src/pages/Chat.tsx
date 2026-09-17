import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Download } from 'lucide-react'
import { Alert, Button } from '@/components/ui'
import { Logo } from '@/components/Logo'
import { Composer } from '@/components/chat/Composer'
import { MessageList } from '@/components/chat/MessageList'
import { Sidebar } from '@/components/sidebar/Sidebar'
import { ConversationUsage } from '@/components/chat/Usage'
import { NewsStrip } from '@/components/news/NewsStrip'
import { Suggestions } from '@/components/chat/Suggestions'
import { useChat } from '@/hooks/useChat'
import { useConversations } from '@/hooks/useConversations'
import { useConfig } from '@/hooks/useConfig'

export default function Chat() {
  const { conversationId: routeId } = useParams<{ conversationId: string }>()
  const navigate = useNavigate()
  const list = useConversations()
  const config = useConfig()
  const [loadError, setLoadError] = useState<string | null>(null)

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
    navigate('/')
  }

  async function remove(id: string) {
    await list.remove(id)
    if (id === chat.conversationId || id === routeId) startNew()
  }

  const activeId = chat.conversationId ?? routeId ?? null
  const empty = chat.messages.length === 0

  return (
    <div className="flex h-dvh overflow-hidden">
      <Sidebar
        conversations={list.conversations}
        activeId={activeId}
        loading={list.loading}
        onSelect={(id) => navigate(`/c/${id}`)}
        onNew={startNew}
        onRename={list.rename}
        onDelete={remove}
      />

      <main className="flex min-w-0 flex-1 flex-col">
        {!empty && (
          <header className="flex h-12 shrink-0 items-center justify-between gap-4 border-b border-border px-4">
            <h1 className="truncate text-sm font-medium">{chat.title}</h1>
            <div className="flex shrink-0 items-center gap-3">
              {chat.totals && <ConversationUsage totals={chat.totals} />}
            {activeId && (
              // A plain link, not fetch-and-blob: the browser already knows how
              // to save a file the server marked as an attachment.
              <a
                href={`/api/conversations/${activeId}/export`}
                download
                className="shrink-0"
                title="Export as Markdown"
              >
                <Button variant="ghost" size="sm">
                  <Download className="size-4" aria-hidden />
                  Export
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

        <Composer
          onSend={(text, options) => chat.send(text, { useSearch: options.useSearch })}
          onStop={chat.stop}
          streaming={chat.streaming}
          searchEnabled={config?.search_enabled ?? false}
          autoFocus
        />
      </main>
    </div>
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

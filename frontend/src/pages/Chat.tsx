import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Alert } from '@/components/ui'
import { Composer } from '@/components/chat/Composer'
import { MessageList } from '@/components/chat/MessageList'
import { Sidebar } from '@/components/sidebar/Sidebar'
import { useChat } from '@/hooks/useChat'
import { useConversations } from '@/hooks/useConversations'
import { Logo } from '@/components/Logo'

export default function Chat() {
  const { conversationId: routeId } = useParams<{ conversationId: string }>()
  const navigate = useNavigate()
  const list = useConversations()
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

  function open(id: string) {
    navigate(`/c/${id}`)
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
        activeId={chat.conversationId ?? routeId ?? null}
        loading={list.loading}
        onSelect={open}
        onNew={startNew}
        onRename={list.rename}
        onDelete={remove}
      />

      <main className="flex min-w-0 flex-1 flex-col">
        {empty ? <EmptyState /> : <MessageList messages={chat.messages} />}

        {(loadError || chat.error) && (
          <div className="mx-auto w-full max-w-[var(--message-column)] px-4">
            <Alert>{loadError ?? chat.error}</Alert>
          </div>
        )}

        <Composer
          onSend={chat.send}
          onStop={chat.stop}
          streaming={chat.streaming}
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

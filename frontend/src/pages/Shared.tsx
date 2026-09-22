import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { FileText } from 'lucide-react'
import { Logo } from '@/components/Logo'
import { Alert, Spinner } from '@/components/ui'
import { Markdown } from '@/components/chat/Markdown'
import { Sources } from '@/components/chat/Sources'
import { apiFetch } from '@/lib/api'
import type { Source } from '@/lib/chat-types'

interface PublicMessage {
  role: string
  content: string
  created_at: string
  sources: Source[]
  documents: { filename: string; unit: string; unit_count: number; thumbnail: string | null }[]
}

interface PublicConversation {
  title: string
  messages: PublicMessage[]
  shared_at: string
  message_count: number
}

/**
 * A shared conversation, read-only, for anyone with the link.
 *
 * Outside `Protected` on purpose — the whole point is that no account is
 * needed. It renders with the same Markdown and citation components as the real
 * chat so a shared answer reads identically, but there is no composer, no
 * sidebar and nothing to click through to: this page can do exactly one thing.
 */
export default function Shared() {
  const { token = '' } = useParams()
  const [conversation, setConversation] = useState<PublicConversation | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    apiFetch<PublicConversation>(`/shares/${encodeURIComponent(token)}`)
      .then((found) => !cancelled && setConversation(found))
      .catch((err) => {
        if (!cancelled) {
          setError(
            err instanceof Error
              ? err.message
              : 'This link is not available. It may have been revoked.',
          )
        }
      })
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [token])

  useEffect(() => {
    if (conversation) document.title = `${conversation.title} · Pelita`
  }, [conversation])

  if (loading) {
    return (
      <main className="flex min-h-dvh items-center justify-center">
        <Spinner />
      </main>
    )
  }

  if (error || !conversation) {
    return (
      <main className="mx-auto flex min-h-dvh max-w-md flex-col items-center justify-center gap-4 px-6 text-center">
        <Logo className="size-10" />
        <Alert tone="info">{error}</Alert>
        <Link to="/" className="text-sm text-primary underline-offset-4 hover:underline">
          Go to Pelita
        </Link>
      </main>
    )
  }

  return (
    <div className="min-h-dvh bg-background">
      <header className="sticky top-0 z-10 border-b border-border bg-surface/80 backdrop-blur">
        <div className="mx-auto flex max-w-3xl items-center gap-3 px-6 py-3">
          <Logo className="size-6 shrink-0" />
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-sm font-medium">{conversation.title}</h1>
            <p className="truncate text-xs text-muted-foreground">
              Shared conversation ·{' '}
              {new Date(conversation.shared_at).toLocaleDateString(undefined, {
                day: 'numeric',
                month: 'long',
                year: 'numeric',
              })}
            </p>
          </div>
          <Link
            to="/"
            className="shrink-0 rounded-lg border border-border px-3 py-1.5 text-xs font-medium hover:border-hover-border hover:bg-hover"
          >
            Try Pelita
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-3xl space-y-6 px-6 py-8">
        {conversation.messages.map((message, index) => (
          <PublicTurn key={index} message={message} />
        ))}

        <p className="border-t border-border pt-6 text-center text-xs text-muted-foreground">
          This is a copy of a conversation, shared by its author. It is read-only and
          does not update.
        </p>
      </main>
    </div>
  )
}

function PublicTurn({ message }: { message: PublicMessage }) {
  if (message.role === 'user') {
    return (
      <div>
        {message.documents.length > 0 && (
          <div className="mb-1.5 flex flex-wrap justify-end gap-2">
            {message.documents.map((document) => (
              <SharedAttachment key={document.filename} document={document} />
            ))}
          </div>
        )}
        <div className="flex justify-end">
          <div className="max-w-[85%] rounded-2xl rounded-br-md bg-bubble-user px-4 py-2.5 text-bubble-user-foreground">
            <p className="whitespace-pre-wrap text-[0.9375rem] leading-relaxed">
              {message.content}
            </p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div>
      <Markdown content={message.content} sources={message.sources} />
      {message.sources.length > 0 && <Sources sources={message.sources} />}
    </div>
  )
}

function SharedAttachment({
  document,
}: {
  document: PublicMessage['documents'][number]
}) {
  return (
    <div className="flex max-w-[15rem] items-center gap-2.5 rounded-xl border border-border bg-surface-raised px-3 py-2">
      {document.thumbnail ? (
        <img
          src={document.thumbnail}
          alt={document.filename}
          className="size-8 shrink-0 rounded-lg object-cover"
        />
      ) : (
        <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-primary/10">
          <FileText className="size-4 text-primary" aria-hidden />
        </span>
      )}
      <span className="min-w-0">
        <span className="block truncate text-[0.8125rem] font-medium leading-tight">
          {document.filename}
        </span>
        <span className="block truncate text-xs text-muted-foreground">
          {document.unit === 'image'
            ? 'image'
            : `${document.unit_count} ${document.unit}${document.unit_count === 1 ? '' : 's'}`}
        </span>
      </span>
    </div>
  )
}

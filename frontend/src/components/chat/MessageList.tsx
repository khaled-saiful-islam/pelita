import { useEffect, useRef } from 'react'
import { AlertCircle } from 'lucide-react'
import { Logo } from '@/components/Logo'
import { Markdown } from './Markdown'
import { MessageActions } from './MessageActions'
import { MessageUsage } from './Usage'
import { Sources } from './Sources'
import { ToolActivityList } from './ToolActivity'
import { GuardBanner } from './GuardBanner'
import { ImageGrid } from './ImageGrid'
import { MessageAttachments } from './Attachments'
import { ArtifactCard } from '@/components/artifacts/ArtifactCard'
import { cn } from '@/lib/utils'
import type { ChatMessage, Rating } from '@/hooks/useChat'

export function MessageList({
  messages,
  ratings,
  currency,
  onRate,
  onRegenerate,
  openArtifact,
  onOpenArtifact,
  footer,
}: {
  messages: ChatMessage[]
  ratings: Record<string, Rating>
  currency: string
  onRate: (messageId: string, rating: Rating | null, reason?: string) => void
  onRegenerate: (messageId: string) => void
  openArtifact?: string | null
  onOpenArtifact?: (artifactId: string | null) => void
  /** Rendered after the last message — follow-up chips live here. */
  footer?: React.ReactNode
}) {
  const bottom = useRef<HTMLDivElement>(null)
  const container = useRef<HTMLDivElement>(null)
  const pinned = useRef(true)

  // Follow the stream, but stop following the moment the reader scrolls up —
  // yanking someone back to the bottom while they are reading is worse than
  // making them scroll down themselves.
  useEffect(() => {
    const el = container.current
    if (!el) return
    const onScroll = () => {
      const distance = el.scrollHeight - el.scrollTop - el.clientHeight
      pinned.current = distance < 80
    }
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => el.removeEventListener('scroll', onScroll)
  }, [])

  useEffect(() => {
    if (pinned.current) bottom.current?.scrollIntoView({ block: 'end' })
  }, [messages])

  return (
    <div ref={container} className="flex-1 overflow-y-auto">
      <div className="mx-auto w-full max-w-[var(--message-column)] px-4 py-8">
        <div className="space-y-7">
          {messages.map((message, index) => (
            <MessageRow
              key={message.id}
              message={message}
              rating={ratings[message.id] ?? null}
              currency={currency}
              // Only the latest answer can be regenerated: redoing an earlier
              // one would orphan every exchange after it.
              canRegenerate={index === messages.length - 1 && message.role === 'assistant'}
              onRate={onRate}
              onRegenerate={onRegenerate}
              openArtifact={openArtifact}
              onOpenArtifact={onOpenArtifact}
            />
          ))}
        </div>
        {footer}
        <div ref={bottom} className="h-px" />
      </div>
    </div>
  )
}

function MessageRow({
  message,
  rating,
  currency,
  canRegenerate,
  onRate,
  onRegenerate,
  openArtifact,
  onOpenArtifact,
}: {
  message: ChatMessage
  rating: Rating | null
  currency: string
  canRegenerate: boolean
  onRate: (messageId: string, rating: Rating | null, reason?: string) => void
  onRegenerate: (messageId: string) => void
  openArtifact?: string | null
  onOpenArtifact?: (artifactId: string | null) => void
}) {
  if (message.role === 'user') {
    return (
      <div>
        {message.documents && message.documents.length > 0 && (
          <MessageAttachments files={message.documents} />
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

  const waiting = message.streaming && message.content.length === 0

  return (
    <div className="group/message">
      {message.guards && message.guards.length > 0 && (
        <GuardBanner alerts={message.guards} />
      )}

      {message.tools && message.tools.length > 0 && (
        <ToolActivityList activities={message.tools} />
      )}

      {message.images && message.images.length > 0 && (
        <ImageGrid images={message.images} />
      )}

      {message.building && (
        <ArtifactCard build={message.building} onOpen={() => onOpenArtifact?.(null)} />
      )}

      {message.artifacts?.map((artifact) => (
        <ArtifactCard
          key={artifact.id}
          artifact={artifact}
          active={openArtifact === artifact.id}
          onOpen={() => onOpenArtifact?.(artifact.id)}
        />
      ))}

      {waiting ? (
        <Working />
      ) : (
        <div className={cn('min-w-0', message.streaming && 'streaming-caret')}>
          <Markdown content={message.content} sources={message.sources ?? []} />
        </div>
      )}

      {message.sources && message.sources.length > 0 && (
        <Sources sources={message.sources} />
      )}

      {message.finish_reason === 'stopped' && (
        <p className="mt-2 text-xs text-muted-foreground">Stopped by you.</p>
      )}

      {message.error && (
        <p className="mt-2 inline-flex items-center gap-1.5 text-xs text-destructive">
          <AlertCircle className="size-3.5" aria-hidden />
          {message.error}
        </p>
      )}

      {!message.streaming && message.content.length > 0 && (
        <div className="mt-1 flex flex-wrap items-center gap-x-3">
          <MessageActions
            content={message.content}
            rating={rating}
            canRegenerate={canRegenerate}
            onRate={(next, reason) => onRate(message.id, next, reason)}
            onRegenerate={() => onRegenerate(message.id)}
          />
          <MessageUsage
            message={message}
            currency={currency}
            className="reveal-on-hover opacity-0 transition-opacity group-hover/message:opacity-100"
          />
        </div>
      )}
    </div>
  )
}

/** Shown between sending and the first token. */
function Working() {
  return (
    <div className="flex items-center gap-2" role="status" aria-live="polite">
      <Logo className="size-4 animate-pulse" />
      <span className="shimmer text-sm">Thinking…</span>
    </div>
  )
}

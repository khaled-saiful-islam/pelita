import { useEffect, useRef, useState } from 'react'
import { Check, Copy, RefreshCw, ThumbsDown, ThumbsUp } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { Rating } from '@/hooks/useChat'

/**
 * Hover actions under an assistant message.
 *
 * Visible on hover and on keyboard focus — `focus-within` is what keeps them
 * reachable without a mouse, which is easy to lose when actions are hover-only.
 */
export function MessageActions({
  content,
  rating,
  canRegenerate,
  onRate,
  onRegenerate,
}: {
  content: string
  rating: Rating | null
  canRegenerate: boolean
  onRate: (rating: Rating | null, reason?: string) => void
  onRegenerate: () => void
}) {
  const [copied, setCopied] = useState(false)
  const [askingWhy, setAskingWhy] = useState(false)

  async function copy() {
    try {
      await navigator.clipboard.writeText(content)
      setCopied(true)
      setTimeout(() => setCopied(false), 1600)
    } catch {
      // Clipboard access can be denied; failing silently beats an alert.
    }
  }

  function rate(next: Rating) {
    if (rating === next) {
      onRate(null) // Clicking the active thumb clears it.
      setAskingWhy(false)
      return
    }
    onRate(next)
    setAskingWhy(next === 'down')
  }

  return (
    <div className="mt-2">
      <div
        className={cn(
          'reveal-on-hover flex items-center gap-0.5 transition-opacity',
          'opacity-0 group-hover/message:opacity-100 focus-within:opacity-100',
          (rating || copied) && 'opacity-100',
        )}
      >
        <ActionButton label={copied ? 'Copied' : 'Copy'} onClick={copy} active={copied}>
          {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
        </ActionButton>

        {canRegenerate && (
          <ActionButton label="Regenerate" onClick={onRegenerate}>
            <RefreshCw className="size-3.5" />
          </ActionButton>
        )}

        <ActionButton
          label="Good response"
          onClick={() => rate('up')}
          active={rating === 'up'}
        >
          <ThumbsUp className="size-3.5" />
        </ActionButton>

        <ActionButton
          label="Bad response"
          onClick={() => rate('down')}
          active={rating === 'down'}
        >
          <ThumbsDown className="size-3.5" />
        </ActionButton>
      </div>

      {askingWhy && (
        <ReasonBox
          onSubmit={(reason) => {
            onRate('down', reason)
            setAskingWhy(false)
          }}
          onDismiss={() => setAskingWhy(false)}
        />
      )}
    </div>
  )
}

function ActionButton({
  label,
  onClick,
  active,
  children,
}: {
  label: string
  onClick: () => void
  active?: boolean
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      aria-pressed={active}
      className={cn(
        'grid size-7 place-items-center rounded-md transition-colors',
        active ? 'text-primary' : 'text-muted-foreground hover:bg-hover hover:text-foreground',
      )}
    >
      {children}
    </button>
  )
}

/** Optional "what went wrong?" — the reasons are the point, not the counts. */
function ReasonBox({
  onSubmit,
  onDismiss,
}: {
  onSubmit: (reason: string) => void
  onDismiss: () => void
}) {
  const [reason, setReason] = useState('')
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => input.current?.focus(), [])

  return (
    <div className="mt-2 flex items-center gap-2 rounded-lg border border-border bg-surface p-2">
      <input
        ref={input}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') onSubmit(reason)
          if (e.key === 'Escape') onDismiss()
        }}
        placeholder="What was wrong? (optional)"
        aria-label="Reason for the rating"
        maxLength={2000}
        className="min-w-0 flex-1 bg-transparent px-1 text-sm placeholder:text-muted-foreground focus:outline-none"
      />
      <button
        type="button"
        onClick={() => onSubmit(reason)}
        className="rounded px-2 py-1 text-xs font-medium text-primary hover:bg-hover"
      >
        Send
      </button>
      <button
        type="button"
        onClick={onDismiss}
        className="rounded px-2 py-1 text-xs text-muted-foreground hover:bg-hover"
      >
        Skip
      </button>
    </div>
  )
}

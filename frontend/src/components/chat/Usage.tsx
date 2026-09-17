import { cn } from '@/lib/utils'
import type { ChatMessage, Totals } from '@/hooks/useChat'

/** Thousands separators, and no trailing ".0" on whole numbers. */
function tokens(n: number): string {
  return n.toLocaleString()
}

/**
 * Money at the precision the number actually has.
 *
 * A turn can cost $0.000131. Formatting that as $0.00 tells the reader it was
 * free, which is the one thing a cost display must never do.
 */
export function formatCost(value: string | number, currency: string): string {
  const amount = Number(value)
  if (!Number.isFinite(amount)) return '—'
  if (amount === 0) return `0 ${currency}`
  const digits = amount < 0.01 ? 6 : amount < 1 ? 4 : 2
  return `${amount.toFixed(digits)} ${currency}`
}

/** Per-message counts, shown alongside the hover actions. */
export function MessageUsage({
  message,
  currency,
  className,
}: {
  message: ChatMessage
  currency: string
  className?: string
}) {
  if (!message.usage_source) return null
  const estimated = message.usage_source === 'estimated'

  return (
    <span
      className={cn('text-xs text-muted-foreground tabular-nums', className)}
      title={
        estimated
          ? 'This provider does not report usage while streaming, so these counts were estimated with tiktoken.'
          : 'Counts reported by the provider.'
      }
    >
      {tokens(message.prompt_tokens)} in · {tokens(message.completion_tokens)} out ·{' '}
      {formatCost(message.cost, currency)}
      {estimated && <span className="ml-1 opacity-70">(est.)</span>}
    </span>
  )
}

/** Conversation totals, shown in the header. */
export function ConversationUsage({ totals }: { totals: Totals }) {
  if (totals.total_tokens === 0) return null

  return (
    <span
      className="hidden text-xs text-muted-foreground tabular-nums sm:inline"
      title={
        totals.estimated
          ? 'Includes at least one estimated figure, so this total is approximate.'
          : 'Every figure reported by the provider.'
      }
    >
      {tokens(totals.total_tokens)} tokens · {formatCost(totals.cost, totals.currency)}
      {totals.estimated && <span className="ml-1 opacity-70">approx.</span>}
    </span>
  )
}

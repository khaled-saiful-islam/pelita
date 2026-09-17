import { useRef, useState } from 'react'
import { ExternalLink } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { Source } from '@/hooks/useChat'

const OPEN_DELAY_MS = 120
const CLOSE_DELAY_MS = 140

/**
 * A numbered citation chip with a preview on hover.
 *
 * The native `title` attribute technically works, but it waits about a second,
 * renders as an unstyled OS tooltip, and shows one line of text. Checking a
 * source should not require a click or a wait — the point of a citation is that
 * it is cheap to verify.
 */
export function Citation({ rank, source }: { rank: number; source: Source }) {
  const [open, setOpen] = useState(false)
  const timer = useRef<number | null>(null)

  function schedule(next: boolean) {
    if (timer.current !== null) window.clearTimeout(timer.current)
    // A small delay each way: opening instantly makes the text twitch as the
    // pointer crosses it, and closing instantly makes the card impossible to
    // move onto.
    timer.current = window.setTimeout(
      () => setOpen(next),
      next ? OPEN_DELAY_MS : CLOSE_DELAY_MS,
    )
  }

  return (
    <span
      className="relative inline-block"
      onMouseEnter={() => schedule(true)}
      onMouseLeave={() => schedule(false)}
    >
      <a
        href={source.url}
        target="_blank"
        rel="noreferrer noopener"
        aria-label={`Source ${rank}: ${source.title}`}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        className={cn(
          'mx-0.5 inline-flex min-w-[1.25rem] items-center justify-center rounded',
          'bg-muted px-1 align-super text-[0.6875rem] font-medium leading-4 tabular-nums',
          'text-muted-foreground no-underline transition-colors',
          'hover:bg-primary hover:text-primary-foreground',
          open && 'bg-primary text-primary-foreground',
        )}
      >
        {rank}
      </a>

      {open && (
        <span
          role="tooltip"
          className={cn(
            'absolute bottom-full left-1/2 z-30 mb-1.5 w-72 -translate-x-1/2',
            'rounded-lg border border-border bg-surface p-3 text-left shadow-lg',
            // The column is centred and narrow, so a card near the edge would
            // otherwise sit half outside it.
            'max-w-[min(18rem,calc(100vw-2rem))]',
          )}
        >
          <span className="flex items-center gap-1 text-[0.6875rem] text-muted-foreground">
            <span className="truncate">{hostOf(source.url)}</span>
            <ExternalLink className="size-2.5 shrink-0" aria-hidden />
          </span>

          <span className="mt-1 block text-sm font-medium leading-snug">{source.title}</span>

          {source.snippet && (
            <span className="mt-1.5 block text-xs leading-relaxed text-muted-foreground line-clamp-4">
              {source.snippet}
            </span>
          )}
        </span>
      )}
    </span>
  )
}

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

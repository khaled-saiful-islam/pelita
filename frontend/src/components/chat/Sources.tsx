import { useState } from 'react'
import { ChevronDown, ExternalLink } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { Source } from '@/hooks/useChat'

/**
 * Citations under an answer.
 *
 * Collapsed by default so a long source list does not push the next question
 * off the screen, and numbered to match the [1] [2] markers in the text.
 */
export function Sources({ sources }: { sources: Source[] }) {
  const [open, setOpen] = useState(false)
  if (sources.length === 0) return null

  return (
    <div className="mt-3">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
      >
        <ChevronDown className={cn('size-3.5 transition-transform', open && 'rotate-180')} aria-hidden />
        {sources.length} source{sources.length === 1 ? '' : 's'}
      </button>

      {open && (
        <ol className="mt-2 space-y-1.5">
          {sources.map((source) => (
            <li key={source.rank}>
              <a
                href={source.url}
                target="_blank"
                rel="noreferrer noopener"
                className="group/source flex gap-2 rounded-lg border border-border bg-surface p-2.5 transition-colors hover:border-hover-border hover:bg-hover"
              >
                <span className="mt-0.5 shrink-0 text-xs tabular-nums text-muted-foreground">
                  [{source.rank}]
                </span>
                <span className="min-w-0">
                  <span className="flex items-center gap-1 text-sm font-medium">
                    <span className="truncate">{source.title}</span>
                    <ExternalLink
                      className="size-3 shrink-0 opacity-0 transition-opacity group-hover/source:opacity-60"
                      aria-hidden
                    />
                  </span>
                  <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                    {hostOf(source.url)}
                  </span>
                  {source.snippet && (
                    <span className="mt-1 block text-xs leading-relaxed text-muted-foreground line-clamp-2">
                      {source.snippet}
                    </span>
                  )}
                </span>
              </a>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

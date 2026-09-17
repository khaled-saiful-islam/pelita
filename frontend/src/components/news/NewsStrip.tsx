import { useEffect, useState } from 'react'
import { ExternalLink } from 'lucide-react'
import { apiFetch } from '@/lib/api'

interface NewsItem {
  title: string
  url: string
  source: string
  published_at: string | null
  snippet: string
}

/**
 * Headlines above the composer on the new-chat screen.
 *
 * Renders nothing at all when news is unavailable — no empty state, no error,
 * no placeholder. It is a decoration, and a decoration that announces its own
 * failure is worse than one that quietly steps aside.
 */
export function NewsStrip() {
  const [items, setItems] = useState<NewsItem[] | null>(null)

  useEffect(() => {
    let cancelled = false
    apiFetch<{ items: NewsItem[] }>('/news')
      .then((data) => {
        if (!cancelled) setItems(data.items)
      })
      .catch(() => {
        if (!cancelled) setItems([])
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (!items || items.length === 0) return null

  return (
    <section
      aria-label="Today's headlines"
      className="mx-auto w-full max-w-[var(--message-column)] px-4 pb-3"
    >
      <h2 className="mb-2 px-1 text-xs font-medium text-muted-foreground">In the news</h2>
      <div className="-mx-1 flex snap-x gap-2 overflow-x-auto px-1 pb-1">
        {items.map((item) => (
          <a
            key={item.url}
            href={item.url}
            target="_blank"
            rel="noreferrer noopener"
            className="group/card flex w-56 shrink-0 snap-start flex-col rounded-xl border border-border bg-surface p-3 transition-colors hover:bg-muted"
          >
            <span className="flex items-center gap-1 text-[0.6875rem] font-medium uppercase tracking-wide text-muted-foreground">
              <span className="truncate">{item.source}</span>
              <ExternalLink
                className="size-2.5 shrink-0 opacity-0 transition-opacity group-hover/card:opacity-60"
                aria-hidden
              />
            </span>
            <span className="mt-1.5 line-clamp-3 text-sm leading-snug">
              {stripSource(item.title, item.source)}
            </span>
          </a>
        ))}
      </div>
    </section>
  )
}

/** Google News titles end in " - Publisher", which the card already shows. */
function stripSource(title: string, source: string): string {
  const suffix = ` - ${source}`
  return title.endsWith(suffix) ? title.slice(0, -suffix.length) : title
}

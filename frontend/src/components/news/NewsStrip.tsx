import { useEffect, useState } from 'react'
import { ArrowUpRight, ChevronLeft, ChevronRight, MessageCircleQuestion, Sparkles } from 'lucide-react'
import { apiFetch } from '@/lib/api'
import { cn } from '@/lib/utils'

interface NewsItem {
  title: string
  url: string
  source: string
  published_at: string | null
  snippet: string
}

interface NewsResponse {
  items: NewsItem[]
  cached: boolean
  /** Non-empty when headlines were chosen from what Pelita remembers. */
  topic: string
}

/** How long a story leads before the next one takes over. */
const LEAD_MS = 7000
const MAX_STORIES = 6

/**
 * The news, as a briefing rather than a row of cards.
 *
 * A strip of six identical grey cards at the top of the screen read as
 * something that had wandered in from another page, and nothing on it asked
 * to be touched. This leads with one story at a time, set large, in a card
 * tinted by its source, and turns to the next every few seconds; the next
 * three wait beside it. And every story can become a conversation — "Ask
 * Pelita about this" is the reason a headline belongs in a chat app at all.
 *
 * Pointing at it, or tabbing into it, holds the story that is showing. With
 * reduced motion it never turns on its own.
 *
 * Renders nothing when news is unavailable — no empty state, no error. It is
 * a decoration, and one that announces its own failure is worse than one that
 * quietly steps aside.
 */
export function NewsStrip({ onAsk }: { onAsk?: (headline: string, source: string) => void }) {
  const [data, setData] = useState<NewsResponse | null>(null)

  useEffect(() => {
    let cancelled = false
    apiFetch<NewsResponse>('/news')
      .then((response) => {
        if (!cancelled) setData(response)
      })
      .catch(() => {
        if (!cancelled) setData(null)
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (!data || data.items.length === 0) return null
  return <Briefing items={data.items.slice(0, MAX_STORIES)} topic={data.topic} onAsk={onAsk} />
}

function Briefing({
  items,
  topic,
  onAsk,
}: {
  items: NewsItem[]
  topic: string
  onAsk?: (headline: string, source: string) => void
}) {
  const [at, setAt] = useState(0)
  const [held, setHeld] = useState(false)
  const still = useReducedMotion()
  const count = items.length

  useEffect(() => {
    if (held || still || count < 2) return
    const timer = window.setTimeout(() => {
      if (!document.hidden) setAt((n) => (n + 1) % count)
    }, LEAD_MS)
    return () => window.clearTimeout(timer)
  }, [at, held, still, count])

  const lead = items[at]
  const headline = stripSource(lead.title, lead.source)
  const next = [1, 2, 3].map((step) => (at + step) % count).filter((i) => i !== at)
  const go = (index: number) => setAt(((index % count) + count) % count)

  return (
    <section
      aria-label="In the news"
      className="mx-auto w-full max-w-[var(--message-column)] px-4"
      onMouseEnter={() => setHeld(true)}
      onMouseLeave={() => setHeld(false)}
      onFocus={() => setHeld(true)}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setHeld(false)
      }}
    >
      <div className="news-brief" style={{ ['--hue' as string]: hueOf(lead.source) }}>
        <header className="flex items-center gap-2">
          <span className="news-live" aria-hidden />
          <h2 className="shrink-0 whitespace-nowrap text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
            In the news
          </h2>
          {topic && (
            <span
              className="inline-flex min-w-0 items-center gap-1 truncate rounded-full bg-accent-100 px-2 py-0.5 text-[0.6875rem] font-medium text-accent-800"
              title="Chosen from what Pelita remembers about you. Edit that in Settings."
            >
              <Sparkles className="size-2.5 shrink-0" aria-hidden />
              <span className="truncate">For you · {topic}</span>
            </span>
          )}

          {count > 1 && (
            <div className="ml-auto flex shrink-0 items-center gap-1">
              <div className="mr-1 hidden items-center gap-1 sm:flex" role="tablist" aria-label="Stories">
                {items.map((item, index) => (
                  <button
                    key={item.url}
                    type="button"
                    role="tab"
                    aria-selected={index === at}
                    aria-label={`Story ${index + 1} of ${count}`}
                    onClick={() => go(index)}
                    className="news-dot"
                    data-on={index === at}
                  >
                    {index === at && (
                      <span
                        key={at}
                        className="news-dot-fill"
                        data-held={held || still}
                        style={{ animationDuration: `${LEAD_MS}ms` }}
                      />
                    )}
                  </button>
                ))}
              </div>
              <Step label="Previous story" onClick={() => go(at - 1)}>
                <ChevronLeft className="size-3.5" aria-hidden />
              </Step>
              <Step label="Next story" onClick={() => go(at + 1)}>
                <ChevronRight className="size-3.5" aria-hidden />
              </Step>
            </div>
          )}
        </header>

        <div className="mt-3 grid gap-4 sm:grid-cols-[minmax(0,1fr)_13rem]">
          {/* Keyed by the story, so each one arrives rather than swapping in. */}
          <article key={lead.url} className="news-lead min-w-0">
            <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <SourceBadge source={lead.source} />
              <span className="truncate font-medium text-foreground/80">{lead.source}</span>
              {lead.published_at && (
                <>
                  <span aria-hidden>·</span>
                  <time dateTime={lead.published_at}>{when(lead.published_at)}</time>
                </>
              )}
            </div>

            <a
              href={lead.url}
              target="_blank"
              rel="noreferrer noopener"
              className="news-headline mt-1.5 line-clamp-2 font-serif text-[1.15rem] font-semibold leading-snug tracking-[-0.005em] sm:text-[1.3rem]"
            >
              {headline}
            </a>

            <div className="mt-3 flex flex-wrap items-center gap-2">
              {onAsk && (
                <button
                  type="button"
                  onClick={() => onAsk(headline, lead.source)}
                  className="news-ask"
                >
                  <MessageCircleQuestion className="size-3.5" aria-hidden />
                  Ask Pelita about this
                </button>
              )}
              <a
                href={lead.url}
                target="_blank"
                rel="noreferrer noopener"
                className="inline-flex items-center gap-1 rounded-full px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-hover hover:text-foreground"
              >
                Read at {lead.source}
                <ArrowUpRight className="size-3" aria-hidden />
              </a>
            </div>
          </article>

          {next.length > 0 && (
            <aside aria-label="Up next" className="hidden min-w-0 border-l border-border/70 pl-4 sm:block">
              <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                Up next
              </p>
              <ul className="space-y-1">
                {next.map((index) => {
                  const item = items[index]
                  return (
                    <li key={item.url}>
                      <button
                        type="button"
                        onClick={() => go(index)}
                        className="news-next group/next flex w-full items-start gap-2 rounded-lg px-1.5 py-1 text-left"
                      >
                        <SourceBadge source={item.source} />
                        <span className="line-clamp-2 text-xs leading-snug text-muted-foreground transition-colors group-hover/next:text-foreground">
                          {stripSource(item.title, item.source)}
                        </span>
                      </button>
                    </li>
                  )
                })}
              </ul>
            </aside>
          )}
        </div>
      </div>
    </section>
  )
}

function Step({
  label,
  onClick,
  children,
}: {
  label: string
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      className={cn(
        'grid size-7 place-items-center rounded-full border border-border bg-surface/80',
        'text-muted-foreground transition-colors hover:bg-hover hover:text-foreground',
      )}
    >
      {children}
    </button>
  )
}

function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(
    () => typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches,
  )
  useEffect(() => {
    const query = window.matchMedia?.('(prefers-reduced-motion: reduce)')
    if (!query) return
    const change = () => setReduced(query.matches)
    query.addEventListener('change', change)
    return () => query.removeEventListener('change', change)
  }, [])
  return reduced
}

/** A hue per source, so the card is tinted by who is speaking. */
function hueOf(source: string): number {
  return [...source].reduce((total, char) => total + char.charCodeAt(0), 0) % 360
}

/**
 * A coloured initial instead of a real favicon.
 *
 * Fetching favicons would leak every headline's domain to a third party on page
 * load, which is not a trade a self-hosted template should make for the sake of
 * a 16px image.
 */
function SourceBadge({ source }: { source: string }) {
  return (
    <span
      aria-hidden
      className="mt-px grid size-4 shrink-0 place-items-center rounded text-[0.5625rem] font-semibold text-white"
      style={{ backgroundColor: `hsl(${hueOf(source)} 55% 45%)` }}
    >
      {source.charAt(0).toUpperCase()}
    </span>
  )
}

/** Google News titles end in " - Publisher", which the card already shows. */
export function stripSource(title: string, source: string): string {
  const suffix = ` - ${source}`
  return title.endsWith(suffix) ? title.slice(0, -suffix.length) : title
}

/**
 * When, the way a person says it.
 *
 * "437d ago" is arithmetic, not an answer. Recent is relative; anything past
 * a week is a date, with the year only when it is not this one.
 */
export function when(value: string, now: Date = new Date()): string {
  const then = new Date(value)
  if (Number.isNaN(then.getTime())) return ''
  const minutes = Math.round((now.getTime() - then.getTime()) / 60_000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.round(hours / 24)
  if (days < 7) return `${days}d ago`
  return then.toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
    ...(then.getFullYear() !== now.getFullYear() && { year: 'numeric' }),
  })
}

import { useCallback, useEffect, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight, Sparkles } from 'lucide-react'
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

const SCROLL_STEP = 320

/**
 * Headlines across the top of the new-chat screen.
 *
 * Renders nothing at all when news is unavailable — no empty state, no error,
 * no skeleton. It is a decoration, and a decoration that announces its own
 * failure is worse than one that quietly steps aside.
 */
export function NewsStrip() {
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

  return (
    <section
      aria-label="Headlines"
      className="mx-auto w-full max-w-[var(--message-column)] px-4 pb-3"
    >
      <Header topic={data.topic} />
      <Carousel items={data.items} />
    </section>
  )
}

function Header({ topic }: { topic: string }) {
  return (
    <div className="mb-2 flex items-center gap-2 px-1">
      <h2 className="text-xs font-medium text-muted-foreground">In the news</h2>
      {topic && (
        <span
          className="inline-flex items-center gap-1 rounded-full bg-accent-100 px-2 py-0.5 text-[0.6875rem] font-medium text-accent-800"
          title="Chosen from what Pelita remembers about you. Edit that in Settings."
        >
          <Sparkles className="size-2.5" aria-hidden />
          {topic}
        </span>
      )}
    </div>
  )
}

function Carousel({ items }: { items: NewsItem[] }) {
  const track = useRef<HTMLDivElement>(null)
  const [atStart, setAtStart] = useState(true)
  const [atEnd, setAtEnd] = useState(false)

  const measure = useCallback(() => {
    const el = track.current
    if (!el) return
    setAtStart(el.scrollLeft <= 1)
    // A pixel of slack: fractional widths mean scrollLeft rarely lands exactly.
    setAtEnd(el.scrollLeft + el.clientWidth >= el.scrollWidth - 1)
  }, [])

  useEffect(() => {
    measure()
    const el = track.current
    if (!el) return

    el.addEventListener('scroll', measure, { passive: true })
    // Arrows must also update when the container resizes, not only on scroll —
    // otherwise rotating a phone leaves a stale arrow.
    const observer = new ResizeObserver(measure)
    observer.observe(el)
    return () => {
      el.removeEventListener('scroll', measure)
      observer.disconnect()
    }
  }, [measure, items])

  function scrollBy(direction: -1 | 1) {
    track.current?.scrollBy({ left: direction * SCROLL_STEP, behavior: 'smooth' })
  }

  return (
    <div className="group/carousel relative">
      <Arrow side="left" hidden={atStart} onClick={() => scrollBy(-1)} />
      <Arrow side="right" hidden={atEnd} onClick={() => scrollBy(1)} />

      <div
        ref={track}
        className="no-scrollbar flex snap-x snap-mandatory gap-2 overflow-x-auto scroll-smooth"
      >
        {items.map((item) => (
          <Card key={item.url} item={item} />
        ))}
      </div>
    </div>
  )
}

function Arrow({
  side,
  hidden,
  onClick,
}: {
  side: 'left' | 'right'
  hidden: boolean
  onClick: () => void
}) {
  const Icon = side === 'left' ? ChevronLeft : ChevronRight
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={side === 'left' ? 'Previous headlines' : 'More headlines'}
      // Removed from the tree at the ends, so it cannot be tabbed to or clicked
      // when there is nothing left to scroll.
      hidden={hidden}
      className={cn(
        // Always visible when there is somewhere to scroll. Hover-gated arrows
        // do not exist on a touch screen, and are guesswork on a desktop.
        'absolute top-1/2 z-10 grid -translate-y-1/2',
        'size-8 place-items-center rounded-full border border-border bg-surface shadow',
        'text-muted-foreground transition-colors hover:bg-hover hover:text-foreground',
        // Tucked outside the track where there is room, overlapping the edge on
        // a narrow screen rather than being pushed off it.
        side === 'left' ? 'left-1 sm:-left-3' : 'right-1 sm:-right-3',
      )}
    >
      <Icon className="size-4" aria-hidden />
    </button>
  )
}

function Card({ item }: { item: NewsItem }) {
  return (
    <a
      href={item.url}
      target="_blank"
      rel="noreferrer noopener"
      className={cn(
        'group/card flex w-[13.5rem] shrink-0 snap-start flex-col rounded-xl border border-border bg-surface p-3',
        'transition-all hover:-translate-y-0.5 hover:border-primary/30 hover:shadow',
      )}
    >
      <div className="flex items-center gap-1.5">
        <SourceBadge source={item.source} />
        <span className="truncate text-[0.6875rem] font-medium text-muted-foreground">
          {item.source}
        </span>
      </div>

      <p className="mt-2 line-clamp-3 text-sm leading-snug group-hover/card:text-foreground">
        {stripSource(item.title, item.source)}
      </p>

      {item.published_at && (
        <span className="mt-auto pt-2 text-[0.6875rem] text-muted-foreground">
          {relativeTime(item.published_at)}
        </span>
      )}
    </a>
  )
}

/**
 * A coloured initial instead of a real favicon.
 *
 * Fetching favicons would leak every headline's domain to a third party on page
 * load, which is not a trade a self-hosted template should make for the sake of
 * a 16px image.
 */
function SourceBadge({ source }: { source: string }) {
  const hue = [...source].reduce((total, char) => total + char.charCodeAt(0), 0) % 360
  return (
    <span
      aria-hidden
      className="grid size-4 shrink-0 place-items-center rounded text-[0.5625rem] font-semibold text-white"
      style={{ backgroundColor: `hsl(${hue} 55% 45%)` }}
    >
      {source.charAt(0).toUpperCase()}
    </span>
  )
}

/** Google News titles end in " - Publisher", which the card already shows. */
function stripSource(title: string, source: string): string {
  const suffix = ` - ${source}`
  return title.endsWith(suffix) ? title.slice(0, -suffix.length) : title
}

function relativeTime(value: string): string {
  const then = new Date(value).getTime()
  if (Number.isNaN(then)) return ''

  const minutes = Math.round((Date.now() - then) / 60_000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`

  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.round(hours / 24)}d ago`
}

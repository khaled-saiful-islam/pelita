import { useEffect, useRef } from 'react'
import { cn } from '@/lib/utils'
import type { SlideSummary } from '@/lib/deck'

/**
 * The slides along the bottom, as they actually look.
 *
 * Real thumbnails rather than numbered dots: in a deck of twelve, "which one
 * had the chart" is the question people are actually asking, and a row of
 * identical circles cannot answer it.
 *
 * Each one is the same document translated to its own slide, so the browser
 * fetches and lays it out once and the rest are cheap.
 */
const THUMB_WIDTH = 132

export function DeckFilmstrip({
  html,
  slides,
  width,
  height,
  current,
  sandbox,
  onPick,
}: {
  html: string
  slides: SlideSummary[]
  width: number
  height: number
  current: number
  sandbox: string
  onPick: (index: number) => void
}) {
  const strip = useRef<HTMLDivElement>(null)
  const scale = THUMB_WIDTH / width

  // Keep the one being looked at in view, including when the arrow keys are
  // doing the walking.
  useEffect(() => {
    strip.current?.querySelector(`[data-slide="${current}"]`)?.scrollIntoView({
      behavior: 'smooth',
      block: 'nearest',
      inline: 'center',
    })
  }, [current])

  if (slides.length < 2) return null

  return (
    <div
      ref={strip}
      className="flex shrink-0 gap-2 overflow-x-auto border-t border-border bg-background px-3 py-2.5"
      role="tablist"
      aria-label="Slides"
    >
      {slides.map((slide) => (
        <button
          key={slide.index}
          type="button"
          data-slide={slide.index}
          role="tab"
          aria-selected={slide.index === current}
          aria-label={`Slide ${slide.index + 1}: ${slide.heading}`}
          title={slide.heading}
          onClick={() => onPick(slide.index)}
          className={cn(
            'group relative shrink-0 overflow-hidden rounded-md ring-1 transition-all',
            slide.index === current
              ? 'ring-2 ring-primary'
              : 'ring-border opacity-70 hover:opacity-100',
          )}
          style={{ width: THUMB_WIDTH, height: height * scale }}
        >
          <iframe
            aria-hidden
            tabIndex={-1}
            title={slide.heading}
            srcDoc={html}
            sandbox={sandbox}
            referrerPolicy="no-referrer"
            // Pointer events off so the click lands on the button, not in a
            // frame that would swallow it.
            style={{
              width,
              height: height * slides.length,
              transform: `scale(${scale}) translateY(${-slide.index * height}px)`,
              transformOrigin: 'top left',
              border: 0,
              display: 'block',
              pointerEvents: 'none',
            }}
          />
          <span className="absolute bottom-0 right-0 rounded-tl bg-background/85 px-1 text-[10px] tabular-nums">
            {slide.index + 1}
          </span>
        </button>
      ))}
    </div>
  )
}

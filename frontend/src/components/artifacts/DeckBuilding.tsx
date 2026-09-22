import { useEffect, useRef, useState } from 'react'
import { Check, Loader2 } from 'lucide-react'
import { readableOn } from '@/lib/contrast'
import type { ArtifactBuild } from '@/lib/chat-types'

/**
 * A deck being written.
 *
 * Three things go up before any slide exists: what the talk is called, what it
 * argues, and what it is going to look like. Then every slide is named, and
 * each card fills with the real thing as it lands.
 *
 * Shown in the deck's own palette rather than in grey. A progress display in
 * somebody else's colours is a progress display for something else, and the
 * colours are known a full minute before the slides are.
 */

export function DeckBuilding({ build }: { build: ArtifactBuild }) {
  const planned = build.plan ?? []
  const made = new Map(build.parts.map((part) => [part.index, part]))
  const total = planned.length || build.parts.length
  const design = build.design
  const ground = design?.palette?.[0] ?? '#ffffff'
  // Picked by contrast, not by position: a palette is a list, not named roles,
  // and a deck whose first two colours were both cream put cream on cream.
  const ink = design ? readableOn(ground, design.palette.slice(1)) : undefined
  const accent = design?.palette?.find(
    (colour) => colour !== ground && colour !== ink,
  )

  // The grid reflows with the panel, so the thumbnails are scaled from what a
  // card actually measures rather than from a number picked in advance.
  const grid = useRef<HTMLDivElement>(null)
  const [scale, setScale] = useState(0.1125)
  useEffect(() => {
    const element = grid.current
    if (!element) return
    const measure = () => {
      const card = element.firstElementChild?.firstElementChild
      const width = card?.getBoundingClientRect().width ?? 0
      if (width > 0) setScale(width / 1600)
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
  }, [total])

  if (!total && !design) return null

  return (
    <div className="space-y-5">
      {design && (
        <div
          className="rounded-lg border p-4"
          style={{
            // The deck's own ground and ink, so what is on screen already
            // belongs to the thing being made.
            background: ground,
            borderColor: `${accent ?? ink ?? '#888'}33`,
            color: ink,
          }}
        >
          <div className="flex items-baseline justify-between gap-3">
            <p className="text-sm font-medium" style={{ fontFamily: design.display_font }}>
              {design.movement}
            </p>
            <p className="shrink-0 text-[11px] opacity-70">
              {design.display_font} · {design.body_font}
            </p>
          </div>
          <div className="mt-3 flex gap-1.5">
            {design.palette.slice(0, 7).map((colour) => (
              <span
                key={colour}
                title={colour}
                className="h-5 flex-1 rounded"
                style={{ background: colour }}
              />
            ))}
          </div>
        </div>
      )}

      {total > 0 && (
        <>
          <div className="flex items-center gap-3">
            <div className="h-1 flex-1 overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full transition-[width] duration-500 ease-out"
                style={{
                  width: `${(made.size / total) * 100}%`,
                  background: accent ?? 'hsl(var(--primary))',
                }}
              />
            </div>
            <span className="shrink-0 font-mono text-[11px] tabular-nums text-muted-foreground">
              {made.size} / {total}
            </span>
          </div>

          {made.size < total && (
            <p className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="size-3 shrink-0 animate-spin text-primary" aria-hidden />
              <span className="shimmer">
                Writing slide {made.size + 1}
                {planned[made.size] ? ` — ${planned[made.size]}` : ''}
              </span>
            </p>
          )}

          {/* Only the slides that exist. An empty grey rectangle is not a
              preview of anything, and a screen of them is not progress. */}
          {made.size > 0 && (
            <div
              ref={grid}
              className="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-x-3 gap-y-4"
              style={{ ['--thumb-scale' as string]: String(scale) }}
            >
              {build.parts.map((part) => (
                <div key={part.index} className="min-w-0">
                  <div
                    className="arriving relative overflow-hidden rounded-md shadow-md ring-1 ring-border"
                    style={{ aspectRatio: '16 / 9' }}
                  >
                    <SlideThumb html={part.html} />
                    <span className="absolute bottom-0 right-0 rounded-tl bg-background/85 px-1 text-[10px] tabular-nums">
                      {part.index + 1}
                    </span>
                  </div>
                  <p className="mt-1.5 flex items-start gap-1 text-xs leading-snug">
                    <Check className="mt-[3px] size-3 shrink-0 text-success" aria-hidden />
                    <span className="line-clamp-2 min-w-0">{part.title}</span>
                  </p>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}

/** One finished slide, small. Its own document, so it looks like itself. */
function SlideThumb({ html }: { html: string }) {
  return (
    <iframe
      aria-hidden
      tabIndex={-1}
      title=""
      srcDoc={html}
      sandbox=""
      referrerPolicy="no-referrer"
      style={{
        width: 1600,
        height: 900,
        // Scaled by the container rather than a fixed number, so the grid can
        // reflow at any panel width without the thumbnails lying about it.
        transform: 'scale(var(--thumb-scale, 0.1125))',
        transformOrigin: 'top left',
        border: 0,
        display: 'block',
        pointerEvents: 'none',
      }}
    />
  )
}

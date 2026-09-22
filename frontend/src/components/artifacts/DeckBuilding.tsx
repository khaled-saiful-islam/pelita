import { useEffect, useRef, useState } from 'react'
import { Check, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
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
const RATIO = 9 / 16

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

          <div
            ref={grid}
            className="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-x-3 gap-y-4"
            style={{ ['--thumb-scale' as string]: String(scale) }}
          >
            {Array.from({ length: total }, (_, index) => {
              const part = made.get(index)
              const next = !part && index === made.size
              const heading = part?.title ?? planned[index] ?? `Slide ${index + 1}`
              return (
                <div key={index} className="min-w-0">
                  <div
                    className={cn(
                      'relative overflow-hidden rounded-md ring-1 transition-all duration-500',
                      part ? 'arriving shadow-md ring-border' : 'ring-border/50',
                      next && 'ring-2',
                    )}
                    style={{
                      aspectRatio: `${1 / RATIO}`,
                      ...(next && accent ? { borderColor: accent, boxShadow: `0 0 0 2px ${accent}55` } : {}),
                      ...(part ? {} : { background: design?.palette?.[0] ?? undefined }),
                    }}
                  >
                    {part ? (
                      <SlideThumb html={part.html} />
                    ) : (
                      <span
                        className={cn(
                          'absolute inset-0',
                          next ? 'shimmer' : 'opacity-40',
                        )}
                        style={{ background: design?.palette?.[0] ?? 'hsl(var(--muted))' }}
                      />
                    )}
                    <span className="absolute bottom-0 right-0 rounded-tl bg-background/85 px-1 text-[10px] tabular-nums">
                      {index + 1}
                    </span>
                  </div>
                  <p className="mt-1.5 flex items-start gap-1 text-xs leading-snug">
                    <span className="mt-[3px] shrink-0">
                      {part ? (
                        <Check className="size-3 text-success" aria-hidden />
                      ) : next ? (
                        <Loader2 className="size-3 animate-spin text-primary" aria-hidden />
                      ) : (
                        <span className="block size-3" />
                      )}
                    </span>
                    <span
                      className={cn(
                        'line-clamp-2 min-w-0',
                        part ? 'text-foreground' : 'text-muted-foreground',
                      )}
                    >
                      {heading}
                    </span>
                  </p>
                </div>
              )
            })}
          </div>
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

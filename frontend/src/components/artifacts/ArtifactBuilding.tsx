import { useEffect, useRef, useState } from 'react'
import { Check, Loader2 } from 'lucide-react'
import { readableOn } from '@/lib/contrast'
import { Forming } from '@/components/artifacts/Forming'
import type { ArtifactBuild } from '@/lib/chat-types'

/**
 * An artifact being made.
 *
 * A deck shows every slide as it lands. A poster has nothing to show until it
 * is finished, so it gets its look instead — the palette and the two faces,
 * decided a full minute before anything else exists. Never the source:
 * watching markup scroll past is not a preview of anything.
 *
 * A game gets neither. Its swatches say nothing about it, and the one line
 * worth reading — what the player actually does — is already in the step
 * above.
 *
 * What is shown is shown in the artifact's own palette rather than in grey. A
 * progress display in somebody else's colours is a progress display for
 * something else.
 */

export function ArtifactBuilding({ build }: { build: ArtifactBuild }) {
  const planned = build.plan ?? []
  const made = new Map(build.parts.map((part) => [part.index, part]))
  const total = planned.length || build.parts.length
  const design = build.design
  // The card is a poster's only preview: it has no pieces to show as they
  // land, so its palette is the one thing there is to look at while it works.
  // A deck already shows real slides, and for a game the swatches say nothing
  // the step above has not — its loop is named there, in a sentence. The
  // colours are still read from the design either way, because the progress
  // bar belongs to the thing being made.
  // Until there are real pieces to show. A deck replaces it with its own
  // slides as they land; a poster and a game keep it to the end, because
  // neither has anything to show before it is finished.
  const showLook = made.size === 0
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

  if (!total && !showLook) return null

  return (
    <div className="space-y-5">
      {/* Never a row of swatches. That a palette was chosen is a fact about
          the artifact, not a picture of it. */}
      {showLook && <Forming build={build} />}

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

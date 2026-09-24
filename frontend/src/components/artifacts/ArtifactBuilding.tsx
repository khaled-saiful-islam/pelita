import { useEffect, useRef, useState } from 'react'
import { Check, Loader2 } from 'lucide-react'
import { accentOn, readableOn } from '@/lib/contrast'
import { Forming } from '@/components/artifacts/Forming'
import { arrivesInPieces } from '@/components/artifacts/arrives-in-pieces'
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

/** The panel's ground in light mode, which is where the chips are read. */
const PANEL = '#fdfcfa'

export function ArtifactBuilding({ build }: { build: ArtifactBuild }) {
  const planned = build.plan ?? []
  const made = new Map(build.parts.map((part) => [part.index, part]))
  const total = planned.length || build.parts.length
  const design = build.design
  // Until there are real pieces to show. A deck replaces the card with its own
  // slides as they land; a poster and a game keep it to the end, because
  // neither has anything to show before it is finished.
  const showLook = made.size === 0
  const piecemeal = arrivesInPieces(build)
  const ground = design?.palette?.[0] ?? '#ffffff'
  // Picked by contrast, not by position: a palette is a list, not named roles,
  // and a deck whose first two colours were both cream put cream on cream.
  const ink = design ? readableOn(ground, design.palette.slice(1)) : undefined
  // The chips sit on the panel, not on the card, so they are measured against
  // the panel's own ground rather than the artifact's.
  const accent = design ? accentOn(PANEL, ink ?? '#111111', design.palette) : undefined
  // What each piece is called, and the shape it is drawn at: a deck's slides
  // are widescreen, a website's pages are the top of a desktop screen.
  const noun = build.kind === 'website' ? 'page' : 'slide'
  const thumb = { width: build.width || 1600, height: build.height || 900 }

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
      if (width > 0) setScale(width / thumb.width)
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
    // Measured once the grid exists, not when the plan arrives: before the
    // first piece lands there is no grid to measure, and the default only
    // happened to suit a deck's narrowest cards.
  }, [total, thumb.width, made.size > 0])

  if (!total && !showLook) return null

  return (
    <div className="space-y-5">
      {/* Never a row of swatches. That a palette was chosen is a fact about
          the artifact, not a picture of it. */}
      {showLook && <Forming build={build} />}

      {planned.length > 0 && !piecemeal && (
        <div className="flex flex-wrap gap-1.5" aria-label="What it will contain">
          {planned.map((name, index) => (
            <span
              key={`${name}-${index}`}
              className="rounded-full border px-2.5 py-1 text-[11px]"
              style={{
                borderColor: `${accent ?? 'currentColor'}44`,
                color: accent ?? undefined,
              }}
            >
              {name}
            </span>
          ))}
        </div>
      )}

      {total > 0 && piecemeal && (
        <>
          {made.size < total && (
            <p className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="size-3 shrink-0 animate-spin text-primary" aria-hidden />
              <span className="shimmer">
                Writing {noun} {made.size + 1}
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
                    style={{ aspectRatio: `${thumb.width} / ${thumb.height}` }}
                  >
                    <SlideThumb html={part.html} width={thumb.width} height={thumb.height} />
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
function SlideThumb({ html, width, height }: { html: string; width: number; height: number }) {
  return (
    <iframe
      aria-hidden
      tabIndex={-1}
      title=""
      srcDoc={html}
      sandbox=""
      referrerPolicy="no-referrer"
      style={{
        width,
        height,
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

import { useEffect, useRef, useState } from 'react'
import { ArrowUpRight, Sparkles } from 'lucide-react'
import { colourOf } from '@/components/artifacts/kind-look'
import { Scene } from '@/components/make/Scene'
import { showcaseOf, type Makeable } from '@/components/make/showcase'

/** How long each tile holds the light before it moves on. */
const SPOTLIGHT_MS = 3400

/**
 * What Pelita can make, on the new-chat screen, where the decision is made.
 *
 * Five in a menu were five words nobody opened. Here each kind is a tile in
 * its own colour with a few pixels of what it makes, moving, and a real thing
 * somebody might ask it for. A light moves from tile to tile: the lit one plays
 * its scene and turns to its next example, so the row is never still and never
 * busy — one thing moves at a time, and the eye follows it across.
 *
 * Pointing at a tile takes the light. Choosing one writes its example into
 * the box with the subject selected, so the next thing typed is the person's
 * own subject, or Enter sends the example as it stands.
 */
export function MakeRail({
  kinds,
  onPick,
}: {
  kinds: Makeable[]
  onPick: (kind: Makeable, example: string) => void
}) {
  const [spot, setSpot] = useState(0)
  const spotRef = useRef(0)
  const [held, setHeld] = useState<number | null>(null)
  const [shown, setShown] = useState<number[]>(() => kinds.map(() => 0))

  // Keyed on the names, not the array: a parent that rebuilt the list on
  // every render would otherwise reset the examples every render.
  const names = kinds.map((kind) => kind.name).join(',')
  useEffect(() => setShown(names.split(',').map(() => 0)), [names])

  useEffect(() => {
    if (held !== null || kinds.length === 0) return
    const timer = window.setInterval(() => {
      // Not while the tab is hidden: a light nobody can see is only work.
      if (document.hidden) return
      // Worked out here rather than inside a state updater: updaters must be
      // pure, and one that also set the examples advanced them twice.
      const next = (spotRef.current + 1) % kinds.length
      spotRef.current = next
      setSpot(next)
      setShown((examples) => examples.map((index, i) => (i === next ? index + 1 : index)))
    }, SPOTLIGHT_MS)
    return () => window.clearInterval(timer)
  }, [held, kinds.length])

  if (kinds.length === 0) return null
  const lit = held ?? spot

  return (
    <section aria-label="Make something" className="mb-3">
      <div className="mb-2 flex items-center justify-between px-1">
        <h2 className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
          <Sparkles className="size-3.5 text-primary" aria-hidden />
          Make something
        </h2>
        <span className="hidden text-[11px] text-muted-foreground sm:inline">
          Pick one to start, or just ask
        </span>
      </div>

      <div className="no-scrollbar -mx-1 flex snap-x gap-2 overflow-x-auto px-1 pb-1 pt-1 sm:grid sm:grid-cols-5 sm:overflow-visible">
        {kinds.map((kind, index) => {
          const show = showcaseOf(kind)
          const example = show.examples[shown[index] % show.examples.length] ?? ''
          return (
            <button
              key={kind.name}
              type="button"
              data-live={lit === index}
              onClick={() => onPick(kind, example)}
              onMouseEnter={() => setHeld(index)}
              onMouseLeave={() => setHeld(null)}
              onFocus={() => setHeld(index)}
              onBlur={() => setHeld(null)}
              title={show.promise}
              aria-label={`${kind.label}: ${show.opening}${example}`}
              className="make-tile w-[9.5rem] shrink-0 snap-start sm:w-auto"
              style={{
                ['--tile' as string]: colourOf(kind.name),
                animationDelay: `${index * 70}ms`,
              }}
            >
              <span className="make-stage">
                <Scene kind={kind.name} />
              </span>
              <span className="flex items-center justify-between gap-1 px-1">
                <span className="text-sm font-semibold" style={{ color: 'var(--tile)' }}>
                  {kind.label}
                </span>
                <ArrowUpRight
                  className="size-3.5 shrink-0 text-muted-foreground transition-transform"
                  aria-hidden
                />
              </span>
              <span
                key={example}
                className="make-example px-1 text-[11.5px] leading-snug text-muted-foreground"
              >
                {example}
              </span>
            </button>
          )
        })}
      </div>
    </section>
  )
}

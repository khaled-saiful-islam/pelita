import { cn } from '@/lib/utils'
import type { ArtifactBuild } from '@/lib/chat-types'

/**
 * A deck being written.
 *
 * The plan goes up first — every slide named before any of them exists — and
 * each card fills with the real slide as it lands. Watching a talk take shape
 * is a different thing from watching a spinner, and it is the same
 * information.
 */
const CARD_WIDTH = 210
const RATIO = 9 / 16

export function DeckBuilding({ build }: { build: ArtifactBuild }) {
  const planned = build.plan ?? []
  const made = new Map(build.parts.map((part) => [part.index, part]))
  const total = planned.length || build.parts.length
  if (!total) return null

  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(210px,1fr))] gap-3">
      {Array.from({ length: total }, (_, index) => {
        const part = made.get(index)
        const heading = part?.title ?? planned[index] ?? `Slide ${index + 1}`
        return (
          <div key={index} className="min-w-0">
            <div
              className={cn(
                'relative overflow-hidden rounded-md ring-1 transition-all duration-500',
                part ? 'arriving ring-border shadow-sm' : 'ring-border/60',
              )}
              style={{ height: CARD_WIDTH * RATIO }}
            >
              {part ? (
                <iframe
                  aria-hidden
                  tabIndex={-1}
                  title={heading}
                  srcDoc={part.html}
                  sandbox=""
                  referrerPolicy="no-referrer"
                  style={{
                    width: 1600,
                    height: 900,
                    transform: `scale(${CARD_WIDTH / 1600})`,
                    transformOrigin: 'top left',
                    border: 0,
                    display: 'block',
                    pointerEvents: 'none',
                  }}
                />
              ) : (
                <div className="shimmer h-full w-full bg-muted" />
              )}
              <span className="absolute bottom-0 right-0 rounded-tl bg-background/85 px-1 text-[10px] tabular-nums">
                {index + 1}
              </span>
            </div>
            <p
              className={cn(
                'mt-1.5 line-clamp-2 text-xs',
                part ? 'text-foreground' : 'text-muted-foreground',
              )}
            >
              {heading}
            </p>
          </div>
        )
      })}
    </div>
  )
}

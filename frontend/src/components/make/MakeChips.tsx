import { colourOf, lookOf } from '@/components/artifacts/kind-look'
import type { Makeable } from '@/components/make/showcase'

/**
 * The same five, inside a conversation, where the screen belongs to the talk.
 *
 * One slim row above the box, in the kinds' own colours. It steps aside while
 * something is being typed — `data-typing` on the composer — or while an
 * answer is being written, so it is there when the box is empty and never in
 * the way when it is not.
 */
export function MakeChips({
  kinds,
  hidden,
  onPick,
}: {
  kinds: Makeable[]
  hidden?: boolean
  onPick: (kind: Makeable) => void
}) {
  if (kinds.length === 0) return null
  return (
    <div className="make-chips" data-hidden={hidden ? 'true' : 'false'} aria-hidden={hidden}>
      <div>
        <div
          role="group"
          aria-label="Make something"
          className="no-scrollbar flex items-center gap-1.5 overflow-x-auto px-0.5 pb-2 pt-0.5"
        >
          <span className="mr-0.5 shrink-0 text-[11px] font-medium text-muted-foreground">
            Make
          </span>
          {kinds.map((kind) => {
            const Glyph = lookOf(kind.name).icon
            return (
              <button
                key={kind.name}
                type="button"
                tabIndex={hidden ? -1 : 0}
                onClick={() => onPick(kind)}
                title={kind.description}
                className="make-chip"
                style={{ ['--tile' as string]: colourOf(kind.name) }}
              >
                <span className="make-chip-glyph">
                  <Glyph className="size-3" aria-hidden />
                </span>
                {kind.label}
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}

import { ArrowUpRight } from 'lucide-react'

/**
 * Follow-up chips under the last answer.
 *
 * Shown only on the most recent message: chips under an old answer are stale
 * by definition, and a column full of them is noise.
 */
export function Suggestions({
  items,
  onPick,
  disabled,
}: {
  items: string[]
  onPick: (text: string) => void
  disabled?: boolean
}) {
  if (items.length === 0) return null

  return (
    <div className="mt-4 flex flex-wrap gap-2">
      {items.map((item) => (
        <button
          key={item}
          type="button"
          disabled={disabled}
          onClick={() => onPick(item)}
          className="group/chip inline-flex items-center gap-1.5 rounded-full border border-border bg-surface px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:border-hover-border hover:bg-hover hover:text-foreground disabled:pointer-events-none disabled:opacity-50"
        >
          {item}
          <ArrowUpRight
            className="size-3.5 shrink-0 opacity-0 transition-opacity group-hover/chip:opacity-60"
            aria-hidden
          />
        </button>
      ))}
    </div>
  )
}

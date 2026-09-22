import { useEffect, useRef, useState } from 'react'
import { Image as ImageIcon, Presentation, Sparkles } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface Makeable {
  name: string
  label: string
  description: string
}

/**
 * What this app can make, in the place people look for it.
 *
 * The tools were invisible: the model would design a poster if asked in
 * exactly the right words, and nobody had any way to know that. A menu makes
 * the capability discoverable without crowding the composer, and it is built
 * from what the server says exists — so a kind added to the registry appears
 * here without anybody editing a list.
 *
 * Picking one writes an opening into the box rather than arming a hidden mode.
 * A person can then say what they actually want, and can see exactly what will
 * be sent.
 */
const ICONS: Record<string, typeof ImageIcon> = {
  poster: ImageIcon,
  slides: Presentation,
}

const OPENINGS: Record<string, string> = {
  poster: 'Design a poster for ',
  slides: 'Make a slide deck about ',
}

export function CreateMenu({
  makeable,
  onPick,
}: {
  makeable: Makeable[]
  onPick: (opening: string) => void
}) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const away = (event: MouseEvent) => {
      if (!box.current?.contains(event.target as Node)) setOpen(false)
    }
    const escape = (event: KeyboardEvent) => event.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', away)
    document.addEventListener('keydown', escape)
    return () => {
      document.removeEventListener('mousedown', away)
      document.removeEventListener('keydown', escape)
    }
  }, [open])

  if (makeable.length === 0) return null

  return (
    <div ref={box} className="relative">
      <button
        type="button"
        onClick={() => setOpen((was) => !was)}
        aria-expanded={open}
        aria-haspopup="menu"
        className={cn(
          'flex items-center gap-1.5 rounded-md px-2 py-1 text-xs transition-colors',
          open ? 'bg-muted text-foreground' : 'text-muted-foreground hover:text-foreground',
        )}
      >
        <Sparkles className="size-3.5" aria-hidden />
        Create
      </button>

      {open && (
        <div
          role="menu"
          className="absolute bottom-full left-0 z-30 mb-2 w-72 overflow-hidden rounded-lg border border-border bg-background py-1 shadow-xl"
        >
          {makeable.map((thing) => {
            const Icon = ICONS[thing.name] ?? Sparkles
            return (
              <button
                key={thing.name}
                type="button"
                role="menuitem"
                onClick={() => {
                  onPick(OPENINGS[thing.name] ?? `Make a ${thing.label.toLowerCase()} about `)
                  setOpen(false)
                }}
                className="flex w-full items-start gap-2.5 px-3 py-2.5 text-left hover:bg-hover"
              >
                <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-md bg-muted">
                  <Icon className="size-3.5 text-muted-foreground" aria-hidden />
                </span>
                <span className="min-w-0">
                  <span className="block text-sm font-medium">{thing.label}</span>
                  <span className="block text-xs leading-snug text-muted-foreground">
                    {thing.description}
                  </span>
                </span>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}

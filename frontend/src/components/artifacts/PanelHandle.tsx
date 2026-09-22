import { GripVertical } from 'lucide-react'
import { cn } from '@/lib/utils'

/**
 * The edge you drag to resize the panel.
 *
 * The grip is always visible, not revealed on hover. A control nobody can see
 * is a control nobody uses, and "you can drag this" is not something a person
 * should have to discover by accident.
 *
 * The target is wider than it looks: a one-pixel line is a one-pixel target
 * however carefully it is drawn.
 */
export function PanelHandle({
  dragging,
  onStart,
  onReset,
}: {
  dragging: boolean
  onStart: () => void
  onReset: () => void
}) {
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize the panel"
      tabIndex={0}
      onPointerDown={(event) => {
        event.preventDefault()
        onStart()
      }}
      onDoubleClick={onReset}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') onReset()
      }}
      className="group relative z-10 -mr-2 hidden w-4 shrink-0 cursor-col-resize md:block"
      title="Drag to resize · double-click to reset"
    >
      <span
        aria-hidden
        className={cn(
          'absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-border transition-colors',
          'group-hover:bg-primary/50',
          dragging && 'bg-primary',
        )}
      />
      <span
        aria-hidden
        className={cn(
          'absolute left-1/2 top-1/2 flex h-10 w-4 -translate-x-1/2 -translate-y-1/2',
          'items-center justify-center rounded-full border border-border bg-background',
          'text-muted-foreground shadow-sm transition-colors',
          'group-hover:border-primary/50 group-hover:text-primary',
          dragging && 'border-primary text-primary',
        )}
      >
        <GripVertical className="size-3" />
      </span>
    </div>
  )
}

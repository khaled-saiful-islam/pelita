import { useEffect, useRef } from 'react'
import { Button } from '@/components/ui'

/**
 * Ask before doing something that cannot be undone.
 *
 * Its own file rather than another export from `ui/index.tsx` because it owns
 * behaviour the primitives there do not: it takes the keyboard, puts it back,
 * and closes on Escape.
 *
 * The wording is the caller's job and it matters. "Are you sure?" asks a
 * question nobody can answer — it does not say what will go. Name the thing.
 */
export function Confirm({
  title,
  body,
  confirmLabel = 'Delete',
  destructive = true,
  onConfirm,
  onCancel,
}: {
  title: string
  body?: React.ReactNode
  confirmLabel?: string
  destructive?: boolean
  onConfirm: () => void
  onCancel: () => void
}) {
  const confirmButton = useRef<HTMLButtonElement>(null)
  const returnFocusTo = useRef<Element | null>(null)

  useEffect(() => {
    returnFocusTo.current = document.activeElement
    confirmButton.current?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onCancel()
    }
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
      // Back where they were. Without this the page loses the keyboard
      // entirely and the next Tab starts from the top of the document.
      if (returnFocusTo.current instanceof HTMLElement) returnFocusTo.current.focus()
    }
  }, [onCancel])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onCancel}
    >
      <div
        className="w-full max-w-sm rounded-2xl border border-border bg-surface p-6 shadow-lg"
        onClick={(event) => event.stopPropagation()}
        role="alertdialog"
        aria-modal="true"
        aria-label={title}
      >
        <h2 className="text-base font-semibold">{title}</h2>
        {body && <div className="mt-2 text-sm text-muted-foreground">{body}</div>}

        <div className="mt-6 flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={onCancel}>
            Cancel
          </Button>
          <Button
            ref={confirmButton}
            variant={destructive ? 'danger' : 'primary'}
            size="sm"
            onClick={onConfirm}
          >
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  )
}

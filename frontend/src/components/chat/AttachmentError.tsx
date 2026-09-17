import { AlertCircle, X } from 'lucide-react'

/**
 * A rejected upload, shown in the message column.
 *
 * In the column rather than as a toast: it is a reply to something the user
 * just did, it says what the limit is, and it should stay put until they have
 * read it rather than disappearing on a timer.
 */
export function AttachmentError({
  message,
  onDismiss,
}: {
  message: string
  onDismiss: () => void
}) {
  return (
    <div
      role="alert"
      className="mx-auto w-full max-w-[var(--message-column)] px-4 pb-2"
    >
      <div className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
        <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
        <p className="min-w-0 flex-1">{message}</p>
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss"
          className="grid size-5 shrink-0 place-items-center rounded hover:bg-destructive/10"
        >
          <X className="size-3.5" aria-hidden />
        </button>
      </div>
    </div>
  )
}

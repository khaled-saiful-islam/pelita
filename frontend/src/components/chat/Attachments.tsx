import { FileText, Loader2, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { formatBytes, type AttachedFile } from '@/hooks/useDocuments'

/**
 * "27 lines", "3 pages" — or nothing for an image, where "1 image" says less
 * than the picture next to it already does.
 */
function extent(file: AttachedFile): string {
  if (file.unit === 'image') return formatBytes(file.size_bytes)
  const plural = file.unit_count === 1 ? '' : 's'
  return `${file.unit_count} ${file.unit}${plural}`
}

/**
 * Attached files, in the two places they appear.
 *
 * `Attachments` is the composer: files you have picked but not yet sent, each
 * removable. Inside the composer rather than above it, because they are part of
 * what you are about to send — the same reason a mail client puts attachments
 * in the compose window.
 *
 * `MessageAttachments` is the transcript: once sent, a file becomes a card
 * above the message that sent it and stays there. That is where it belongs —
 * the composer is for what happens next, and a file that never left it reads as
 * one that never arrived.
 */
export function Attachments({
  files,
  uploading,
  onRemove,
}: {
  files: AttachedFile[]
  uploading: string | null
  onRemove: (id: string) => void
}) {
  if (files.length === 0 && !uploading) return null

  return (
    <div className="flex flex-wrap gap-1.5 px-1 pb-2">
      {files.map((file) => (
        <Chip key={file.id} file={file} onRemove={() => onRemove(file.id)} />
      ))}
      {uploading && <Pending name={uploading} />}
    </div>
  )
}

function Chip({ file, onRemove }: { file: AttachedFile; onRemove: () => void }) {
  return (
    <span
      className={cn(
        'group/file inline-flex max-w-[15rem] items-center gap-1.5 rounded-lg',
        'border border-border bg-surface-raised py-1 pl-2 pr-1 text-xs',
      )}
      title={`${file.filename} · ${extent(file)}`}
    >
      {file.thumbnail ? (
        <img
          src={file.thumbnail}
          alt=""
          className="size-4 shrink-0 rounded object-cover"
          aria-hidden
        />
      ) : (
        <FileText className="size-3.5 shrink-0 text-primary" aria-hidden />
      )}
      <span className="truncate font-medium">{file.filename}</span>
      <span className="shrink-0 text-muted-foreground">{extent(file)}</span>
      <button
        type="button"
        onClick={onRemove}
        aria-label={`Remove ${file.filename}`}
        className="grid size-5 shrink-0 place-items-center rounded text-muted-foreground transition-colors hover:bg-hover hover:text-destructive"
      >
        <X className="size-3" aria-hidden />
      </button>
    </span>
  )
}

function Pending({ name }: { name: string }) {
  return (
    <span className="inline-flex max-w-[15rem] items-center gap-1.5 rounded-lg border border-dashed border-border px-2 py-1 text-xs text-muted-foreground">
      <Loader2 className="size-3.5 shrink-0 animate-spin" aria-hidden />
      <span className="truncate">Reading {name}…</span>
    </span>
  )
}


/**
 * Files sent with a message, shown as cards above it.
 *
 * Aligned with the user bubble rather than the column, so the card reads as
 * part of that message. No remove button: the file is in the conversation's
 * history now, and the model has already read it — taking the card away would
 * not take that back.
 */
export function MessageAttachments({ files }: { files: AttachedFile[] }) {
  if (files.length === 0) return null

  return (
    <div className="mb-1.5 flex flex-wrap justify-end gap-2">
      {files.map((file) => (
        <Card key={file.id} file={file} />
      ))}
    </div>
  )
}

function Card({ file }: { file: AttachedFile }) {
  return (
    <div
      className={cn(
        'flex max-w-[15rem] items-center gap-2.5 rounded-xl border border-border',
        'bg-surface-raised px-3 py-2 text-left',
      )}
    >
      {file.thumbnail ? (
        // The original is not stored, so this is the only picture there is —
        // and a card for a photo that shows a document icon reads as a failed
        // upload.
        <img
          src={file.thumbnail}
          alt={file.filename}
          className="size-8 shrink-0 rounded-lg object-cover"
        />
      ) : (
        <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-primary/10">
          <FileText className="size-4 text-primary" aria-hidden />
        </span>
      )}
      <span className="min-w-0">
        <span className="block truncate text-[0.8125rem] font-medium leading-tight">
          {file.filename}
        </span>
        <span className="block truncate text-xs text-muted-foreground">
          {file.unit === 'image' ? extent(file) : `${extent(file)} · ${formatBytes(file.size_bytes)}`}
        </span>
      </span>
    </div>
  )
}

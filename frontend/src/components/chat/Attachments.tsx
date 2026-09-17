import { FileText, Loader2, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { formatBytes, type AttachedFile } from '@/hooks/useDocuments'

/**
 * Attached files, shown inside the composer above the text area.
 *
 * Inside rather than above it, because they are part of what you are about to
 * send — the same reason a mail client puts attachments in the compose window.
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
      title={`${file.filename} · ${file.unit_count} ${file.unit}${
        file.unit_count === 1 ? '' : 's'
      } · ${formatBytes(file.size_bytes)}`}
    >
      <FileText className="size-3.5 shrink-0 text-primary" aria-hidden />
      <span className="truncate font-medium">{file.filename}</span>
      <span className="shrink-0 text-muted-foreground">
        {file.unit_count} {file.unit}
        {file.unit_count === 1 ? '' : 's'}
      </span>
      <button
        type="button"
        onClick={onRemove}
        aria-label={`Remove ${file.filename}`}
        className="grid size-5 shrink-0 place-items-center rounded text-muted-foreground transition-colors hover:bg-muted hover:text-destructive"
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

import { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, apiFetch } from '@/lib/api'
import type { AttachedFile } from '@/lib/chat-types'

export type { AttachedFile } from '@/lib/chat-types'

interface DocumentList {
  items: AttachedFile[]
  max_files: number
  max_bytes: number
}

const DOCUMENT_EXTENSIONS = ['.txt', '.md', '.markdown', '.csv', '.json', '.pdf', '.docx']
const IMAGE_EXTENSIONS = ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp']

/**
 * What the file picker offers, and what the client checks before uploading.
 *
 * Images only when a vision model is configured — offering a picker that
 * accepts a photo the server will refuse is worse than not offering it.
 */
export function acceptAttribute(images: boolean): string {
  return (images ? [...DOCUMENT_EXTENSIONS, ...IMAGE_EXTENSIONS] : DOCUMENT_EXTENSIONS).join(',')
}

export function formatBytes(bytes: number): string {
  const mb = bytes / (1024 * 1024)
  if (mb >= 1) return `${mb.toFixed(1).replace(/\.0$/, '')} MB`
  return `${Math.max(1, Math.round(bytes / 1024))} KB`
}

export interface UseDocuments {
  /** Every file in the conversation — what the limit counts. */
  files: AttachedFile[]
  /** Those not yet sent with a message — what the composer shows. */
  pending: AttachedFile[]
  maxFiles: number
  maxBytes: number
  uploading: string | null
  error: string | null
  attach: (file: File, conversationId: string) => Promise<void>
  remove: (id: string, conversationId: string) => Promise<void>
  /** Move the pending files onto a message, matching what the server just did. */
  markSent: (messageId: string) => void
  clearError: () => void
  reset: () => void
}

/**
 * Files attached to a conversation.
 *
 * A file is uploaded the moment it is picked, before there is a message to hang
 * it on, so it stays *pending* until one is sent. Pending is what the composer
 * shows; sent files have moved to a card in the transcript. The limit counts
 * both, because it is a limit on the conversation, not on the composer.
 *
 * Checks the limits before uploading so a rejected file does not cost a long
 * upload first. The server checks them again — this is a courtesy, not a
 * control.
 */
export function useDocuments(
  conversationId: string | null,
  { images = false }: { images?: boolean } = {},
): UseDocuments {
  const [files, setFiles] = useState<AttachedFile[]>([])
  const [maxFiles, setMaxFiles] = useState(3)
  const [maxBytes, setMaxBytes] = useState(5 * 1024 * 1024)
  const [uploading, setUploading] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!conversationId) {
      setFiles([])
      return
    }
    let cancelled = false
    apiFetch<DocumentList>(`/conversations/${conversationId}/documents`)
      .then((page) => {
        if (cancelled) return
        setFiles(page.items)
        setMaxFiles(page.max_files)
        setMaxBytes(page.max_bytes)
      })
      .catch(() => {
        if (!cancelled) setFiles([])
      })
    return () => {
      cancelled = true
    }
  }, [conversationId])

  const attach = useCallback(
    async (file: File, targetConversationId: string) => {
      setError(null)

      const problem = precheck(file, { files, maxFiles, maxBytes, images })
      if (problem) {
        setError(problem)
        return
      }

      setUploading(file.name)
      try {
        const body = new FormData()
        body.append('file', file)
        const created = await apiFetch<AttachedFile>(
          `/conversations/${targetConversationId}/documents`,
          { method: 'POST', body },
        )
        setFiles((current) => [...current, created])
      } catch (err) {
        setError(
          err instanceof ApiError
            ? err.message
            : `${file.name} could not be uploaded. Check your connection and try again.`,
        )
      } finally {
        setUploading(null)
      }
    },
    [files, maxFiles, maxBytes, images],
  )

  /**
   * Mark the pending files as sent.
   *
   * The server binds them in the same transaction that saves the question; this
   * is the client agreeing immediately, so the chips clear as the message is
   * sent rather than a request later.
   */
  const markSent = useCallback((messageId: string) => {
    setFiles((current) =>
      current.map((f) => (f.message_id === null ? { ...f, message_id: messageId } : f)),
    )
  }, [])

  const remove = useCallback(async (id: string, targetConversationId: string) => {
    const previous = files
    setFiles((current) => current.filter((f) => f.id !== id))
    try {
      await apiFetch<void>(`/conversations/${targetConversationId}/documents/${id}`, {
        method: 'DELETE',
      })
    } catch {
      setFiles(previous)
    }
  }, [files])

  const pending = useMemo(() => files.filter((f) => f.message_id === null), [files])

  return {
    files,
    pending,
    maxFiles,
    maxBytes,
    uploading,
    error,
    attach,
    remove,
    markSent,
    clearError: () => setError(null),
    reset: () => {
      setFiles([])
      setError(null)
    },
  }
}

/** The same rules the server enforces, worded the same way. */
function precheck(
  file: File,
  limits: { files: AttachedFile[]; maxFiles: number; maxBytes: number; images: boolean },
): string | null {
  const extension = file.name.slice(file.name.lastIndexOf('.')).toLowerCase()
  const accepted = limits.images
    ? [...DOCUMENT_EXTENSIONS, ...IMAGE_EXTENSIONS]
    : DOCUMENT_EXTENSIONS
  if (!accepted.includes(extension)) {
    if (!limits.images && IMAGE_EXTENSIONS.includes(extension)) {
      return `${file.name} is an image, and no vision model is configured. Upload plain text, Markdown, CSV, JSON, PDF or Word (.docx).`
    }
    return `${file.name} is not a supported file type. Upload plain text, Markdown, CSV, JSON, PDF or Word (.docx)${limits.images ? ', or an image' : ''}.`
  }
  if (file.size === 0) {
    return `${file.name} is empty.`
  }
  if (file.size > limits.maxBytes) {
    return `${file.name} is ${formatBytes(file.size)}. The limit is ${formatBytes(limits.maxBytes)} per file.`
  }
  if (limits.files.length >= limits.maxFiles) {
    return `This chat already has ${limits.files.length} files, which is the limit. Remove one before adding another.`
  }
  return null
}

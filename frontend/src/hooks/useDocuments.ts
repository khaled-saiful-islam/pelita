import { useCallback, useEffect, useState } from 'react'
import { ApiError, apiFetch } from '@/lib/api'

export interface AttachedFile {
  id: string
  filename: string
  media_type: string
  size_bytes: number
  /** "page" for a PDF, "paragraph" for a docx, "line" for text. */
  unit: string
  unit_count: number
  token_count: number
  created_at: string
}

interface DocumentList {
  items: AttachedFile[]
  max_files: number
  max_bytes: number
}

const ACCEPTED_EXTENSIONS = ['.txt', '.md', '.markdown', '.csv', '.json', '.pdf', '.docx']

/** What the file picker offers, and what the client checks before uploading. */
export const ACCEPT_ATTRIBUTE = ACCEPTED_EXTENSIONS.join(',')

export function formatBytes(bytes: number): string {
  const mb = bytes / (1024 * 1024)
  if (mb >= 1) return `${mb.toFixed(1).replace(/\.0$/, '')} MB`
  return `${Math.max(1, Math.round(bytes / 1024))} KB`
}

export interface UseDocuments {
  files: AttachedFile[]
  maxFiles: number
  maxBytes: number
  uploading: string | null
  error: string | null
  attach: (file: File, conversationId: string) => Promise<void>
  remove: (id: string, conversationId: string) => Promise<void>
  clearError: () => void
  reset: () => void
}

/**
 * Files attached to a conversation.
 *
 * Checks the limits before uploading so a rejected file does not cost a long
 * upload first. The server checks them again — this is a courtesy, not a
 * control.
 */
export function useDocuments(conversationId: string | null): UseDocuments {
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

      const problem = precheck(file, { files, maxFiles, maxBytes })
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
    [files, maxFiles, maxBytes],
  )

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

  return {
    files,
    maxFiles,
    maxBytes,
    uploading,
    error,
    attach,
    remove,
    clearError: () => setError(null),
    reset: () => {
      setFiles([])
      setError(null)
    },
  }
}

/** The same three rules the server enforces, worded the same way. */
function precheck(
  file: File,
  limits: { files: AttachedFile[]; maxFiles: number; maxBytes: number },
): string | null {
  const extension = file.name.slice(file.name.lastIndexOf('.')).toLowerCase()
  if (!ACCEPTED_EXTENSIONS.includes(extension)) {
    return `${file.name} is not a supported file type. Upload plain text, Markdown, CSV, JSON, PDF or Word (.docx).`
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

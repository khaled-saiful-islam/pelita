import { useCallback, useEffect, useState } from 'react'
import { Check, Copy, Link2, Loader2, RefreshCw, Trash2 } from 'lucide-react'
import { Alert, Button } from '@/components/ui'
import { ApiError, apiFetch } from '@/lib/api'

interface Share {
  token: string
  url: string
  title: string
  message_count: number
  view_count: number
  last_viewed_at: string | null
  created_at: string
}

/**
 * Sharing a conversation as a public link.
 *
 * The wording works hard here on purpose: a link that reads as "share with a
 * friend" but behaves as "publish to the internet" is how people leak things.
 * It says plainly that anyone with the link can read it, and that the copy is
 * frozen — because "I deleted that message afterwards" is the assumption this
 * feature would otherwise quietly break.
 */
export function ShareDialog({
  conversationId,
  messageCount,
  onClose,
}: {
  conversationId: string
  messageCount: number
  onClose: () => void
}) {
  const [share, setShare] = useState<Share | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [copied, setCopied] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    apiFetch<Share>(`/conversations/${conversationId}/share`)
      .then((found) => !cancelled && setShare(found))
      .catch((err) => {
        // Not shared yet is the normal case, not a failure worth showing.
        if (!cancelled && !(err instanceof ApiError && err.status === 404)) {
          setError(err instanceof Error ? err.message : 'Could not check this chat.')
        }
      })
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [conversationId])

  const act = useCallback(
    async (method: 'POST' | 'DELETE') => {
      setBusy(true)
      setError(null)
      try {
        const result = await apiFetch<Share | undefined>(
          `/conversations/${conversationId}/share`,
          { method },
        )
        setShare(method === 'DELETE' ? null : (result as Share))
        setCopied(false)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'That did not work.')
      } finally {
        setBusy(false)
      }
    },
    [conversationId],
  )

  async function copy() {
    if (!share) return
    try {
      await navigator.clipboard.writeText(share.url)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Clipboard access can be refused; the link is on screen and selectable.
      setError('Could not copy automatically — select the link and copy it.')
    }
  }

  const stale = share !== null && messageCount > share.message_count

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="w-full max-w-lg rounded-2xl border border-border bg-surface p-6 shadow-lg"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Share this chat"
      >
        <h2 className="flex items-center gap-2 text-lg font-semibold">
          <Link2 className="size-5 text-primary" aria-hidden />
          Share this chat
        </h2>

        {error && (
          <Alert tone="error" className="mt-4">
            {error}
          </Alert>
        )}

        {loading ? (
          <div className="mt-6 flex justify-center">
            <Loader2 className="size-5 animate-spin text-muted-foreground" aria-hidden />
          </div>
        ) : share ? (
          <>
            <p className="mt-3 text-sm text-muted-foreground">
              Anyone with this link can read this chat. They do not need an account, and
              they cannot reply or see anything else of yours.
            </p>

            <div className="mt-4 flex items-center gap-2 rounded-lg border border-border bg-muted px-3 py-2">
              <input
                readOnly
                value={share.url}
                onFocus={(event) => event.currentTarget.select()}
                aria-label="Public link"
                className="min-w-0 flex-1 bg-transparent text-sm outline-none"
              />
              <Button variant="ghost" size="sm" onClick={copy} disabled={busy}>
                {copied ? (
                  <Check className="size-4 text-primary" aria-hidden />
                ) : (
                  <Copy className="size-4" aria-hidden />
                )}
                {copied ? 'Copied' : 'Copy'}
              </Button>
            </div>

            <p className="mt-3 text-xs text-muted-foreground">
              It shows the {share.message_count} message
              {share.message_count === 1 ? '' : 's'} as they were when you shared —
              anything said since stays private until you update it.
              {share.view_count > 0 && ` Opened ${share.view_count} time${share.view_count === 1 ? '' : 's'}.`}
            </p>

            {stale && (
              <Alert tone="info" className="mt-3">
                This chat has {messageCount - share.message_count} newer message
                {messageCount - share.message_count === 1 ? '' : 's'} that the link does
                not include.
              </Alert>
            )}

            <div className="mt-5 flex flex-wrap gap-2">
              <Button variant="outline" onClick={() => void act('POST')} disabled={busy}>
                <RefreshCw className="size-4" aria-hidden />
                Update to latest
              </Button>
              <Button variant="danger" onClick={() => void act('DELETE')} disabled={busy}>
                <Trash2 className="size-4" aria-hidden />
                Stop sharing
              </Button>
              <Button variant="ghost" onClick={onClose} className="ml-auto">
                Done
              </Button>
            </div>
          </>
        ) : (
          <>
            <p className="mt-3 text-sm text-muted-foreground">
              This creates a public link. Anyone who has it can read this conversation
              without signing in, so only share it with people you would show the whole
              chat to.
            </p>
            <p className="mt-2 text-sm text-muted-foreground">
              A copy is taken now. Later messages are not included until you update the
              link, and you can stop sharing at any time.
            </p>
            <div className="mt-5 flex gap-2">
              <Button onClick={() => void act('POST')} loading={busy}>
                <Link2 className="size-4" aria-hidden />
                Create link
              </Button>
              <Button variant="ghost" onClick={onClose}>
                Cancel
              </Button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

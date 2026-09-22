import { useCallback, useEffect, useState } from 'react'
import { Check, Copy, Link2, Loader2, RefreshCw, Trash2 } from 'lucide-react'
import { Alert, Button } from '@/components/ui'
import { ApiError, apiFetch } from '@/lib/api'

interface ArtifactShare {
  token: string
  url: string
  title: string
  version: number
  view_count: number
  created_at: string
}

/**
 * A public link to one poster.
 *
 * Says plainly what it does. A link described as "share" that behaves as
 * "publish" is how people put things on the internet they did not mean to, and
 * the copy being frozen is the part nobody expects unless it is written down.
 */
export function ShareArtifactDialog({
  artifactId,
  version,
  onClose,
}: {
  artifactId: string
  version: number
  onClose: () => void
}) {
  const [share, setShare] = useState<ArtifactShare | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [copied, setCopied] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    apiFetch<ArtifactShare | null>(`/artifacts/${artifactId}/share`)
      .then((found) => !cancelled && setShare(found))
      .catch((err) => {
        // Not shared yet is the normal case, not a failure worth showing.
        if (!cancelled && !(err instanceof ApiError && err.status === 404)) {
          setError(err instanceof Error ? err.message : 'Could not check this poster.')
        }
      })
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [artifactId])

  const act = useCallback(
    async (method: 'POST' | 'DELETE') => {
      setBusy(true)
      setError(null)
      try {
        if (method === 'DELETE') {
          await apiFetch<void>(`/artifacts/${artifactId}/share`, { method })
          setShare(null)
        } else {
          setShare(
            await apiFetch<ArtifactShare>(`/artifacts/${artifactId}/share?version=${version}`, {
              method,
            }),
          )
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'That did not work.')
      } finally {
        setBusy(false)
      }
    },
    [artifactId, version],
  )

  async function copy() {
    if (!share) return
    await navigator.clipboard.writeText(share.url)
    setCopied(true)
    setTimeout(() => setCopied(false), 1600)
  }

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Share this poster"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg rounded-xl border border-border bg-background p-5 shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 className="text-base font-semibold">Share this poster</h2>

        {loading ? (
          <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" aria-hidden /> Checking
          </div>
        ) : share ? (
          <>
            <p className="mt-2 text-sm text-muted-foreground">
              Anyone with this link can see the poster without an account. They cannot see the
              conversation it came from.
            </p>
            <div className="mt-4 flex items-center gap-2">
              <code className="min-w-0 flex-1 truncate rounded-md bg-surface px-3 py-2 text-xs">
                {share.url}
              </code>
              <Button variant="ghost" size="sm" onClick={copy} title="Copy the link">
                {copied ? (
                  <Check className="size-4 text-success" aria-hidden />
                ) : (
                  <Copy className="size-4" aria-hidden />
                )}
              </Button>
            </div>
            <p className="mt-3 text-xs text-muted-foreground">
              It shows version {share.version} as it was when you shared it. Later changes stay
              private until you update the link.
            </p>
            <div className="mt-5 flex items-center justify-between gap-2">
              <div className="flex gap-2">
                <Button variant="ghost" size="sm" disabled={busy} onClick={() => act('POST')}>
                  <RefreshCw className="size-4" aria-hidden /> Update to v{version}
                </Button>
                <Button variant="ghost" size="sm" disabled={busy} onClick={() => act('DELETE')}>
                  <Trash2 className="size-4" aria-hidden /> Stop sharing
                </Button>
              </div>
              <Button size="sm" onClick={onClose}>
                Done
              </Button>
            </div>
          </>
        ) : (
          <>
            <p className="mt-2 text-sm text-muted-foreground">
              Create a link anyone can open. It shows a copy of version {version} — nothing you
              change afterwards appears until you update the link.
            </p>
            <div className="mt-5 flex justify-end gap-2">
              <Button variant="ghost" size="sm" onClick={onClose}>
                Cancel
              </Button>
              <Button size="sm" disabled={busy} onClick={() => act('POST')}>
                <Link2 className="size-4" aria-hidden /> Create a link
              </Button>
            </div>
          </>
        )}

        {error && <Alert className="mt-4">{error}</Alert>}
      </div>
    </div>
  )
}

import { useCallback, useEffect, useRef, useState } from 'react'
import { apiFetch } from '@/lib/api'

/** The most an app may keep. The server refuses more; this avoids asking. */
const MAX_BYTES = 256 * 1024
/** Saves are batched: an app saves after every keystroke if it likes. */
const SAVE_AFTER_MS = 600

/**
 * What an app keeps, on the person's account.
 *
 * The app cannot save anything itself — it runs in a frame with an opaque
 * origin, which is the point of the frame — so it posts what it wants kept to
 * the panel, and the panel keeps it here, for this person and this artifact
 * only. It is put back in front of the app every time the app is opened.
 *
 * `current()` is what the app should open with: the last thing it saved in
 * this session if there is one, otherwise what was loaded. A new version of
 * the app, arriving mid-session after a change in the chat, therefore opens
 * with the tasks typed a minute ago rather than the ones loaded at the start.
 */
export function useAppState(artifactId: string | null) {
  const [ready, setReady] = useState(false)
  const [nonce, setNonce] = useState(0)
  const loaded = useRef<unknown>(null)
  const latest = useRef<unknown>(undefined)
  const pending = useRef<string | null>(null)
  const timer = useRef<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  const flush = useCallback(async () => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current)
      timer.current = null
    }
    const text = pending.current
    pending.current = null
    if (!artifactId || text === null) return
    try {
      await apiFetch<void>(`/artifacts/${artifactId}/state`, {
        method: 'PUT',
        body: JSON.stringify({ data: JSON.parse(text) }),
      })
      setError(null)
    } catch (cause) {
      // Said once, quietly: the app still works, it just may not remember.
      setError(cause instanceof Error ? cause.message : 'Could not save this app’s data.')
    }
  }, [artifactId])

  useEffect(() => {
    setReady(false)
    loaded.current = null
    latest.current = undefined
    if (!artifactId) return
    let cancelled = false
    apiFetch<{ data: unknown }>(`/artifacts/${artifactId}/state`)
      .then((found) => {
        if (!cancelled) loaded.current = found.data ?? null
      })
      .catch(() => {
        // Nothing saved, or not reachable: the app opens with its defaults.
      })
      .finally(() => {
        if (!cancelled) setReady(true)
      })
    return () => {
      cancelled = true
      void flush()
    }
  }, [artifactId, flush])

  const save = useCallback(
    (text: string) => {
      if (text.length > MAX_BYTES) {
        setError('This app is trying to keep more than it is allowed to.')
        return
      }
      try {
        latest.current = JSON.parse(text)
      } catch {
        return
      }
      pending.current = text
      if (timer.current !== null) window.clearTimeout(timer.current)
      timer.current = window.setTimeout(() => void flush(), SAVE_AFTER_MS)
    },
    [flush],
  )

  const reset = useCallback(async () => {
    pending.current = null
    if (timer.current !== null) window.clearTimeout(timer.current)
    latest.current = undefined
    loaded.current = null
    if (artifactId) {
      await apiFetch<void>(`/artifacts/${artifactId}/state`, { method: 'DELETE' }).catch(() => {})
    }
    // A new document, so the frame reloads and the app opens empty.
    setNonce((n) => n + 1)
  }, [artifactId])

  const current = useCallback(
    () => (latest.current !== undefined ? latest.current : loaded.current),
    [],
  )

  return { ready, current, save, reset, nonce, error }
}

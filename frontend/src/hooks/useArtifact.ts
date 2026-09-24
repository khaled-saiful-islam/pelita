import { useCallback, useEffect, useState } from 'react'
import { apiFetch } from '@/lib/api'
import { checkFit, type FitResult } from '@/lib/fit-check'
import type { ArtifactDetail } from '@/lib/chat-types'

/**
 * One artifact, loaded and measured.
 *
 * The document arrives twice by two different routes — streamed while it is
 * made, fetched on every visit afterwards — so this hook is the single place
 * that owns "what is currently on screen", and the panel never has to know
 * which route it came by.
 *
 * `fit` is deliberately undefined until the measurement finishes. The panel
 * waits for it rather than showing a poster and then admitting it is broken.
 */
export function useArtifact(artifactId: string | null, revision = 0) {
  const [artifact, setArtifact] = useState<ArtifactDetail | null>(null)
  const [fit, setFit] = useState<FitResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async (id: string, version?: number) => {
    setLoading(true)
    setError(null)
    setFit(null)
    try {
      const query = version ? `?version=${version}` : ''
      const detail = await apiFetch<ArtifactDetail>(`/artifacts/${id}${query}`)
      setArtifact(detail)
      setLoading(false)

      // Measured alongside, not before. Waiting for fonts to load inside a
      // throwaway frame takes seconds, and a panel that shows nothing for
      // five of them looks broken — which is a worse failure than the one the
      // measurement is looking for, and a far more common one.
      // A poster only. The check measures words against a fixed page's edge,
      // and a website or a game has no such edge: it scrolls, or it plays.
      if (detail.kind !== 'poster') return
      void checkFit(detail.html).then((result) => {
        // Still the same artifact? A fast click through two of them would
        // otherwise pin the first one's verdict onto the second.
        setArtifact((current) => {
          if (current?.id === detail.id && current.version === detail.version) setFit(result)
          return current
        })
      })
    } catch (cause) {
      setError((cause as Error).message)
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!artifactId) {
      setArtifact(null)
      setFit(null)
      return
    }
    void load(artifactId)
    // `revision` is what makes an edit appear. The id does not change when a
    // poster is changed, so without it the panel would keep showing the
    // version it loaded the first time and the version selector would never
    // learn there was a second one.
  }, [artifactId, revision, load])

  return { artifact, fit, error, loading, reload: load }
}

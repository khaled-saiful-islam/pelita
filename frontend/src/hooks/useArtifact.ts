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
export function useArtifact(artifactId: string | null) {
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
      setFit(await checkFit(detail.html))
    } catch (cause) {
      setError((cause as Error).message)
    } finally {
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
  }, [artifactId, load])

  return { artifact, fit, error, loading, reload: load }
}

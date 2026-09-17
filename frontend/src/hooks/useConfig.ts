import { useEffect, useState } from 'react'
import { getConfig, type PublicConfig } from '@/lib/api'

/**
 * Non-secret server configuration.
 *
 * Lets the UI disable what will not work — a search button that always fails is
 * worse than one that says why it is unavailable.
 */
export function useConfig(): PublicConfig | null {
  const [config, setConfig] = useState<PublicConfig | null>(null)

  useEffect(() => {
    let cancelled = false
    getConfig()
      .then((c) => {
        if (!cancelled) setConfig(c)
      })
      .catch(() => {
        if (!cancelled) setConfig(null)
      })
    return () => {
      cancelled = true
    }
  }, [])

  return config
}

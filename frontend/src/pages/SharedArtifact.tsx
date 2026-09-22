import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Alert, Spinner } from '@/components/ui'
import { Logo } from '@/components/Logo'
import { ArtifactFrame } from '@/components/artifacts/ArtifactFrame'

/**
 * A shared poster, to anyone with the link.
 *
 * The document is fetched as text and handed to the same frame the panel uses,
 * so a stranger sees it under exactly the sandbox its kind declared. No
 * sidebar, no composer, and nothing linking back to the conversation it came
 * from.
 */
export default function SharedArtifact() {
  const { token } = useParams<{ token: string }>()
  const [html, setHtml] = useState<string | null>(null)
  const [size, setSize] = useState({ width: 0, height: 0 })
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    fetch(`/api/shares/artifacts/${token}`)
      .then(async (response) => {
        if (!response.ok) throw new Error('This link is not available. It may have been revoked.')
        // The size it chose for itself. It cannot be read out of the document
        // once rendered — that is what the opaque origin is for — so the
        // server says it here.
        setSize({
          width: Number(response.headers.get('X-Artifact-Width') ?? 0),
          height: Number(response.headers.get('X-Artifact-Height') ?? 0),
        })
        return response.text()
      })
      .then((text) => !cancelled && setHtml(text))
      .catch((cause: Error) => !cancelled && setError(cause.message))
    return () => {
      cancelled = true
    }
  }, [token])

  return (
    <div className="flex h-dvh flex-col bg-surface">
      <header className="flex h-12 shrink-0 items-center gap-2 border-b border-border px-4">
        <Logo className="size-5" />
        <span className="text-sm font-medium">Pelita</span>
      </header>

      {error && (
        <div className="mx-auto mt-10 w-full max-w-md px-4">
          <Alert>{error}</Alert>
        </div>
      )}

      {!html && !error && (
        <div className="grid flex-1 place-items-center">
          <Spinner />
        </div>
      )}

      {html && (
        <ArtifactFrame
          html={html}
          width={size.width}
          height={size.height}
          sandbox=""
          title="Shared poster"
        />
      )}
    </div>
  )
}

import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Alert, Spinner } from '@/components/ui'
import { Logo } from '@/components/Logo'
import { ArtifactFrame } from '@/components/artifacts/ArtifactFrame'
import { SiteBar } from '@/components/artifacts/SiteBar'
import { SiteFrame } from '@/components/artifacts/SiteFrame'
import { isApp, isFluid, isSite, sitePages, withState, type Device } from '@/lib/site'

interface Shared {
  html: string
  kind: string
  sandbox: string
  width: number
  height: number
}

/**
 * A shared artifact, to anyone with the link.
 *
 * The document is fetched as text and handed to the same frame the panel uses,
 * so a stranger sees it under exactly the sandbox its kind declared. No
 * sidebar, no composer, and nothing linking back to the conversation it came
 * from.
 *
 * The kind and its sandbox arrive as headers, because nothing can be read out
 * of the document once it is framed. This page used to frame everything with
 * `sandbox=""`, which is right for a poster and meant a shared game could not
 * run and a shared website's menu went nowhere.
 *
 * A shared app is handed out without its owner's data — a shared task board
 * that showed somebody else's tasks would be a leak, not a feature. A visitor
 * has no account to keep theirs on, so it is kept in their own browser.
 */
export default function SharedArtifact() {
  const { token } = useParams<{ token: string }>()
  const [shared, setShared] = useState<Shared | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [device, setDevice] = useState<Device>('desktop')
  const [page, setPage] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    fetch(`/api/shares/artifacts/${token}`)
      .then(async (response) => {
        if (!response.ok) throw new Error('This link is not available. It may have been revoked.')
        const html = await response.text()
        if (cancelled) return
        setShared({
          html,
          kind: response.headers.get('X-Artifact-Kind') ?? '',
          sandbox: response.headers.get('X-Artifact-Sandbox') ?? '',
          width: Number(response.headers.get('X-Artifact-Width') ?? 0),
          height: Number(response.headers.get('X-Artifact-Height') ?? 0),
        })
      })
      .catch((cause: Error) => !cancelled && setError(cause.message))
    return () => {
      cancelled = true
    }
  }, [token])

  const site = isSite(shared?.kind)
  const app = isApp(shared?.kind)
  const fluid = isFluid(shared?.kind)
  const pages = useMemo(() => (shared && site ? sitePages(shared.html) : []), [shared, site])
  const key = `pelita-app:shared:${token}`
  // Read once, when the app arrives; a save must not reload the frame.
  const appHtml = useMemo(
    () => (shared && app ? withState(shared.html, readLocal(key)) : null),
    [shared, app, key],
  )

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

      {!shared && !error && (
        <div className="grid flex-1 place-items-center">
          <Spinner />
        </div>
      )}

      {shared && fluid && (
        <>
          <SiteBar
            pages={pages}
            page={page}
            onPage={setPage}
            device={device}
            onDevice={setDevice}
            fit={app}
          />
          <SiteFrame
            html={appHtml ?? shared.html}
            sandbox={shared.sandbox}
            title={app ? 'Shared app' : 'Shared website'}
            device={device}
            page={page}
            onPage={setPage}
            fit={app}
            onStore={app ? (text) => writeLocal(key, text) : undefined}
          />
        </>
      )}

      {shared && !fluid && (
        <ArtifactFrame
          html={shared.html}
          width={shared.width}
          height={shared.height}
          sandbox={shared.sandbox}
          title={`Shared ${shared.kind || 'artifact'}`}
        />
      )}
    </div>
  )
}

/** What a visitor's copy of a shared app saved, in their own browser. */
function readLocal(key: string): unknown {
  try {
    const text = window.localStorage.getItem(key)
    return text ? JSON.parse(text) : null
  } catch {
    return null
  }
}

function writeLocal(key: string, text: string): void {
  if (text.length > 256 * 1024) return
  try {
    window.localStorage.setItem(key, text)
  } catch {
    // Private mode or full: the app works, it just forgets.
  }
}

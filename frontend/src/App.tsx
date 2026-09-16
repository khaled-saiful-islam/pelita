import { useEffect, useState } from 'react'
import { getConfig, getHealth, type Health, type PublicConfig } from '@/lib/api'
import { cn } from '@/lib/utils'

/**
 * Phase 1 surface: proves the stack is wired end to end — browser to nginx to
 * API to Postgres — before any chat code exists. Replaced by the chat shell in
 * feature 009.
 */
export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [config, setConfig] = useState<PublicConfig | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([getHealth(), getConfig()])
      .then(([h, c]) => {
        setHealth(h)
        setConfig(c)
      })
      .catch((e: Error) => setError(e.message))
  }, [])

  return (
    <main className="min-h-dvh grid place-items-center p-6">
      <div className="w-full max-w-md rounded-xl border bg-surface p-8 shadow">
        <div className="flex items-center gap-3">
          <img src="/pelita.svg" alt="" className="size-8" />
          <h1 className="text-xl font-semibold tracking-tight">
            {config?.app_name ?? 'Pelita'}
          </h1>
        </div>

        <p className="mt-2 text-sm text-muted-foreground">
          Provider-agnostic chatbot template.
        </p>

        <dl className="mt-6 space-y-2 text-sm">
          <Row label="API">
            <Status ok={!!health && !error} label={error ? 'unreachable' : (health?.status ?? '…')} />
          </Row>
          <Row label="Database">
            <Status ok={health?.database === 'ok'} label={health?.database ?? '…'} />
          </Row>
          <Row label="Model">
            <span className="font-mono text-xs">{config?.model ?? '…'}</span>
          </Row>
          <Row label="Web search">
            <Status
              ok={!!config?.search_enabled}
              label={config?.search_enabled ? 'configured' : 'no SERPAPI_KEY'}
            />
          </Row>
        </dl>

        {error && (
          <p className="mt-6 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
            {error}
          </p>
        )}
      </div>
    </main>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <dt className="text-muted-foreground">{label}</dt>
      <dd>{children}</dd>
    </div>
  )
}

function Status({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className={cn('size-1.5 rounded-full', ok ? 'bg-success' : 'bg-muted-foreground/50')}
        aria-hidden
      />
      <span className={cn(!ok && 'text-muted-foreground')}>{label}</span>
    </span>
  )
}

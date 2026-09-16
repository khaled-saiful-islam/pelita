import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { LogOut, User as UserIcon } from 'lucide-react'
import { Button, Card } from '@/components/ui'
import { getConfig, type PublicConfig } from '@/lib/api'
import { useAuth } from '@/lib/auth'

/**
 * Signed-in landing. Replaced by the chat shell in feature 009 — until the chat
 * endpoints exist, this proves the session works and shows what is configured.
 */
export default function Home() {
  const { user, signOut } = useAuth()
  const [config, setConfig] = useState<PublicConfig | null>(null)

  useEffect(() => {
    getConfig().then(setConfig).catch(() => setConfig(null))
  }, [])

  return (
    <main className="mx-auto min-h-dvh w-full max-w-2xl px-6 py-10">
      <header className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <img src="/pelita.svg" alt="" className="size-8" />
          <h1 className="text-xl font-semibold tracking-tight">
            {config?.app_name ?? 'Pelita'}
          </h1>
        </div>
        <div className="flex items-center gap-2">
          <Link to="/profile">
            <Button variant="ghost" size="sm">
              <UserIcon className="size-4" aria-hidden />
              {user?.display_name ?? user?.username}
            </Button>
          </Link>
          <Button variant="ghost" size="icon" onClick={signOut} aria-label="Sign out">
            <LogOut className="size-4" aria-hidden />
          </Button>
        </div>
      </header>

      <Card className="mt-8 p-6">
        <h2 className="font-medium">Configuration</h2>
        <dl className="mt-4 space-y-2 text-sm">
          <Row label="Model">
            <span className="font-mono text-xs">{config?.model ?? '…'}</span>
          </Row>
          <Row label="Web search">
            <span className={config?.search_enabled ? '' : 'text-muted-foreground'}>
              {config?.search_enabled ? 'configured' : 'no SERPAPI_KEY'}
            </span>
          </Row>
          <Row label="Languages">
            <span className="font-mono text-xs">
              {config?.supported_languages.join(', ') ?? '…'}
            </span>
          </Row>
        </dl>
      </Card>
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

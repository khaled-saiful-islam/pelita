import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft, Check } from 'lucide-react'
import { Alert, Button, Card, Field, Input } from '@/components/ui'
import { apiFetch } from '@/lib/api'
import { useAuth, type User } from '@/lib/auth'

export default function Profile() {
  const { user, updateUser } = useAuth()
  if (!user) return null

  return (
    <main className="mx-auto min-h-dvh w-full max-w-2xl px-6 py-10">
      <Link
        to="/"
        className="mb-8 inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" aria-hidden />
        Back to chat
      </Link>

      <h1 className="text-2xl font-semibold tracking-tight">Profile</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        Signed in as <span className="font-mono">{user.username}</span>
        {user.is_admin && (
          <span className="ml-2 rounded bg-accent-100 px-1.5 py-0.5 text-xs font-medium text-accent-800">
            admin
          </span>
        )}
      </p>

      <div className="mt-8 space-y-6">
        <DetailsCard user={user} onSaved={updateUser} />
        <PasswordCard />
        <p className="text-sm text-muted-foreground">
          Looking for memory and theme?{' '}
          <Link to="/settings" className="text-primary hover:underline">
            Settings
          </Link>
        </p>
      </div>
    </main>
  )
}

function DetailsCard({ user, onSaved }: { user: User; onSaved: (u: User) => void }) {
  const [displayName, setDisplayName] = useState(user.display_name ?? '')
  const [email, setEmail] = useState(user.email)
  const form = useSubmit(async () => {
    onSaved(
      await apiFetch<User>('/auth/me', {
        method: 'PATCH',
        body: JSON.stringify({ display_name: displayName, email }),
      }),
    )
  })

  return (
    <Card className="p-6">
      <h2 className="font-medium">Details</h2>
      <form onSubmit={form.submit} className="mt-4 space-y-4">
        <Field label="Display name" htmlFor="display_name">
          <Input
            id="display_name"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            required
            maxLength={120}
          />
        </Field>
        <Field label="Email" htmlFor="profile_email">
          <Input
            id="profile_email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </Field>
        <FormFooter {...form} label="Save changes" savedLabel="Saved" />
      </form>
    </Card>
  )
}

function PasswordCard() {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const form = useSubmit(async () => {
    await apiFetch<void>('/auth/me/password', {
      method: 'POST',
      body: JSON.stringify({ current_password: current, new_password: next }),
    })
    setCurrent('')
    setNext('')
  })

  return (
    <Card className="p-6">
      <h2 className="font-medium">Password</h2>
      <form onSubmit={form.submit} className="mt-4 space-y-4">
        <Field label="Current password" htmlFor="current_password">
          <Input
            id="current_password"
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            required
          />
        </Field>
        <Field label="New password" htmlFor="new_password" hint="At least 8 characters.">
          <Input
            id="new_password"
            type="password"
            autoComplete="new-password"
            minLength={8}
            value={next}
            onChange={(e) => setNext(e.target.value)}
            required
          />
        </Field>
        <FormFooter {...form} label="Change password" savedLabel="Password changed" />
      </form>
    </Card>
  )
}

/** Shared submit/error/saved state, so both cards behave identically. */
function useSubmit(action: () => Promise<void>) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    setSaved(false)
    setBusy(true)
    try {
      await action()
      setSaved(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong.')
    } finally {
      setBusy(false)
    }
  }

  return { submit, busy, error, saved }
}

function FormFooter({
  busy,
  error,
  saved,
  label,
  savedLabel,
}: {
  busy: boolean
  error: string | null
  saved: boolean
  label: string
  savedLabel: string
}) {
  return (
    <>
      {error && <Alert>{error}</Alert>}
      <div className="flex items-center gap-3">
        <Button type="submit" loading={busy}>
          {label}
        </Button>
        {saved && !busy && (
          <span className="inline-flex items-center gap-1.5 text-sm text-success">
            <Check className="size-4" aria-hidden />
            {savedLabel}
          </span>
        )}
      </div>
    </>
  )
}

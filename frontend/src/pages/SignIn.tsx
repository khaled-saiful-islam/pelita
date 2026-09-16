import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Alert, Button, Card, Field, Input } from '@/components/ui'
import { useAuth } from '@/lib/auth'
import { Logo } from '@/components/Logo'

type Mode = 'signin' | 'signup'

export default function SignIn() {
  const [mode, setMode] = useState<Mode>('signin')
  const [identifier, setIdentifier] = useState('')
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const { signIn, signUp } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as { from?: string } | null)?.from ?? '/'

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      if (mode === 'signin') await signIn(identifier, password)
      else await signUp(username, email, password)
      navigate(from, { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong.')
    } finally {
      setBusy(false)
    }
  }

  function switchTo(next: Mode) {
    setMode(next)
    setError(null)
  }

  return (
    <main className="min-h-dvh grid place-items-center p-6">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <Logo className="size-9" />
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Pelita</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {mode === 'signin' ? 'Sign in to continue' : 'Create an account'}
            </p>
          </div>
        </div>

        <Card className="p-6">
          <form onSubmit={submit} className="space-y-4">
            {mode === 'signin' ? (
              <Field label="Username or email" htmlFor="identifier">
                <Input
                  id="identifier"
                  autoComplete="username"
                  autoFocus
                  required
                  value={identifier}
                  onChange={(e) => setIdentifier(e.target.value)}
                />
              </Field>
            ) : (
              <>
                <Field label="Username" htmlFor="username">
                  <Input
                    id="username"
                    autoComplete="username"
                    autoFocus
                    required
                    minLength={2}
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                  />
                </Field>
                <Field label="Email" htmlFor="email">
                  <Input
                    id="email"
                    type="email"
                    autoComplete="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                  />
                </Field>
              </>
            )}

            <Field
              label="Password"
              htmlFor="password"
              hint={mode === 'signup' ? 'At least 8 characters.' : undefined}
            >
              <Input
                id="password"
                type="password"
                autoComplete={mode === 'signin' ? 'current-password' : 'new-password'}
                required
                minLength={mode === 'signup' ? 8 : undefined}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </Field>

            {error && <Alert>{error}</Alert>}

            <Button type="submit" loading={busy} className="w-full">
              {mode === 'signin' ? 'Sign in' : 'Create account'}
            </Button>
          </form>
        </Card>

        <p className="mt-6 text-center text-sm text-muted-foreground">
          {mode === 'signin' ? (
            <>
              No account?{' '}
              <button
                type="button"
                onClick={() => switchTo('signup')}
                className="font-medium text-primary hover:underline"
              >
                Sign up
              </button>
            </>
          ) : (
            <>
              Already have one?{' '}
              <button
                type="button"
                onClick={() => switchTo('signin')}
                className="font-medium text-primary hover:underline"
              >
                Sign in
              </button>
            </>
          )}
        </p>
      </div>
    </main>
  )
}

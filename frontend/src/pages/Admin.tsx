import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft, Check, Plus, ShieldCheck, UserCog, X } from 'lucide-react'
import { Alert, Button, Card, Input, Spinner } from '@/components/ui'
import { apiFetch } from '@/lib/api'
import { cn } from '@/lib/utils'
import { useAuth } from '@/lib/auth'

interface ManagedUser {
  id: string
  username: string
  email: string
  display_name: string | null
  is_admin: boolean
  is_active: boolean
  /** Null is unlimited, which is the default. */
  daily_token_limit: number | null
  tokens_used_24h: number
  created_at: string
}

export default function Admin() {
  const { user } = useAuth()
  const [users, setUsers] = useState<ManagedUser[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const page = await apiFetch<{ items: ManagedUser[] }>('/admin/users')
      setUsers(page.items)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load users.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  /**
   * Applied optimistically then reconciled, because the server may refuse —
   * the last administrator cannot be disabled, and finding that out should not
   * mean the row already looks changed.
   */
  async function patch(id: string, body: Record<string, unknown>) {
    setError(null)
    try {
      const updated = await apiFetch<ManagedUser>(`/admin/users/${id}`, {
        method: 'PATCH',
        body: JSON.stringify(body),
      })
      setUsers((current) => current.map((u) => (u.id === id ? updated : u)))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save that change.')
    }
  }

  return (
    <main className="mx-auto min-h-dvh w-full max-w-4xl px-6 py-10">
      <Link
        to="/"
        className="mb-8 inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" aria-hidden />
        Back to chat
      </Link>

      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="inline-flex items-center gap-2 text-2xl font-semibold tracking-tight">
            <UserCog className="size-6 text-primary" aria-hidden />
            Users
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Anyone can sign up. Here you can also create accounts, switch them off, and
            cap what they spend.
          </p>
        </div>
        <Button onClick={() => setCreating((open) => !open)} className="shrink-0">
          <Plus className="size-4" aria-hidden />
          New user
        </Button>
      </div>

      {error && (
        <Alert tone="error" className="mt-6">
          {error}
        </Alert>
      )}

      {creating && (
        <CreateUser
          onCancel={() => setCreating(false)}
          onCreated={(created) => {
            setUsers((current) => [created, ...current])
            setCreating(false)
          }}
          onError={setError}
        />
      )}

      {loading ? (
        <div className="mt-10 flex justify-center">
          <Spinner />
        </div>
      ) : (
        <ul className="mt-6 space-y-3">
          {users.map((managed) => (
            <UserRow
              key={managed.id}
              user={managed}
              isSelf={managed.id === user?.id}
              onPatch={patch}
            />
          ))}
        </ul>
      )}
    </main>
  )
}

function UserRow({
  user,
  isSelf,
  onPatch,
}: {
  user: ManagedUser
  isSelf: boolean
  onPatch: (id: string, body: Record<string, unknown>) => Promise<void>
}) {
  const [editingLimit, setEditingLimit] = useState(false)

  return (
    <Card className={cn('p-4', !user.is_active && 'opacity-60')}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="flex items-center gap-2 font-medium">
            <span className="truncate">{user.display_name || user.username}</span>
            {user.is_admin && (
              <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-xs text-primary">
                <ShieldCheck className="size-3" aria-hidden />
                Admin
              </span>
            )}
            {!user.is_active && (
              <span className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                Disabled
              </span>
            )}
          </p>
          <p className="truncate text-sm text-muted-foreground">
            {user.username} · {user.email}
          </p>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void onPatch(user.id, { is_admin: !user.is_admin })}
            // The server refuses these too; disabling here just avoids offering
            // someone a button whose only outcome is an error message.
            disabled={isSelf}
            title={isSelf ? 'You cannot change your own role' : undefined}
          >
            {user.is_admin ? 'Remove admin' : 'Make admin'}
          </Button>
          <Button
            variant={user.is_active ? 'outline' : 'primary'}
            onClick={() => void onPatch(user.id, { is_active: !user.is_active })}
            disabled={isSelf}
            title={isSelf ? 'You cannot disable your own account' : undefined}
          >
            {user.is_active ? 'Disable' : 'Enable'}
          </Button>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-border pt-3 text-sm">
        <span className="text-muted-foreground">
          Used in 24h:{' '}
          <span className="tabular-nums text-foreground">
            {user.tokens_used_24h.toLocaleString()}
          </span>
        </span>

        {editingLimit ? (
          <LimitForm
            current={user.daily_token_limit}
            onCancel={() => setEditingLimit(false)}
            onSave={async (limit) => {
              await onPatch(
                user.id,
                limit === null ? { clear_limit: true } : { daily_token_limit: limit },
              )
              setEditingLimit(false)
            }}
          />
        ) : (
          <button
            type="button"
            onClick={() => setEditingLimit(true)}
            className="text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
          >
            Limit:{' '}
            <span className="tabular-nums text-foreground">
              {user.daily_token_limit === null
                ? 'unlimited'
                : user.daily_token_limit.toLocaleString()}
            </span>
          </button>
        )}
      </div>
    </Card>
  )
}

function LimitForm({
  current,
  onSave,
  onCancel,
}: {
  current: number | null
  onSave: (limit: number | null) => Promise<void>
  onCancel: () => void
}) {
  const [value, setValue] = useState(current === null ? '' : String(current))

  return (
    <form
      className="flex items-center gap-2"
      onSubmit={(event) => {
        event.preventDefault()
        const trimmed = value.trim()
        // Empty means unlimited, which is a different request from "set it to
        // zero" — zero stops the account entirely.
        void onSave(trimmed === '' ? null : Number(trimmed))
      }}
    >
      <Input
        type="number"
        min={0}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="unlimited"
        aria-label="Tokens per 24 hours"
        className="w-40"
        autoFocus
      />
      <Button type="submit" variant="ghost" aria-label="Save limit">
        <Check className="size-4" aria-hidden />
      </Button>
      <Button type="button" variant="ghost" onClick={onCancel} aria-label="Cancel">
        <X className="size-4" aria-hidden />
      </Button>
    </form>
  )
}

function CreateUser({
  onCreated,
  onCancel,
  onError,
}: {
  onCreated: (user: ManagedUser) => void
  onCancel: () => void
  onError: (message: string) => void
}) {
  const [form, setForm] = useState({
    username: '',
    email: '',
    password: '',
    daily_token_limit: '',
    is_admin: false,
  })
  const [saving, setSaving] = useState(false)

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setSaving(true)
    try {
      const created = await apiFetch<ManagedUser>('/admin/users', {
        method: 'POST',
        body: JSON.stringify({
          username: form.username.trim(),
          email: form.email.trim(),
          password: form.password,
          is_admin: form.is_admin,
          daily_token_limit:
            form.daily_token_limit.trim() === '' ? null : Number(form.daily_token_limit),
        }),
      })
      onCreated(created)
    } catch (err) {
      onError(err instanceof Error ? err.message : 'Could not create that account.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card className="mt-6 p-6">
      <h2 className="font-medium">New account</h2>
      <form onSubmit={submit} className="mt-4 grid gap-3 sm:grid-cols-2">
        <Input
          value={form.username}
          onChange={(e) => setForm({ ...form, username: e.target.value })}
          placeholder="Username"
          aria-label="Username"
          minLength={3}
          required
        />
        <Input
          type="email"
          value={form.email}
          onChange={(e) => setForm({ ...form, email: e.target.value })}
          placeholder="Email"
          aria-label="Email"
          required
        />
        <Input
          type="password"
          value={form.password}
          onChange={(e) => setForm({ ...form, password: e.target.value })}
          placeholder="Password (at least 8 characters)"
          aria-label="Password"
          minLength={8}
          required
        />
        <Input
          type="number"
          min={0}
          value={form.daily_token_limit}
          onChange={(e) => setForm({ ...form, daily_token_limit: e.target.value })}
          placeholder="Token limit per 24h (blank = unlimited)"
          aria-label="Token limit per 24 hours"
        />
        <label className="flex items-center gap-2 text-sm sm:col-span-2">
          <input
            type="checkbox"
            checked={form.is_admin}
            onChange={(e) => setForm({ ...form, is_admin: e.target.checked })}
            className="size-4 accent-[var(--color-primary)]"
          />
          Make this account an administrator
        </label>
        <div className="flex gap-2 sm:col-span-2">
          <Button type="submit" disabled={saving}>
            {saving ? 'Creating…' : 'Create account'}
          </Button>
          <Button type="button" variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        </div>
      </form>
    </Card>
  )
}

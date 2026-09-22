import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft, Brain, Check, Monitor, Moon, Pencil, Plus, Sun, Trash2, X } from 'lucide-react'
import { Alert, Button, Card, Input, Spinner } from '@/components/ui'
import { apiFetch } from '@/lib/api'
import { cn } from '@/lib/utils'
import { useTheme, type ThemeChoice } from '@/lib/theme'

interface Memory {
  id: string
  content: string
  source: 'user' | 'extracted'
  enabled: boolean
  created_at: string
}

interface MemoryListResponse {
  items: Memory[]
  limit: number
}

export default function Settings() {
  const [memories, setMemories] = useState<Memory[]>([])
  const [limit, setLimit] = useState(100)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [adding, setAdding] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const page = await apiFetch<MemoryListResponse>('/memories')
      setMemories(page.items)
      setLimit(page.limit)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load memories.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  async function add(event: React.FormEvent) {
    event.preventDefault()
    const content = draft.trim()
    if (!content) return
    setError(null)
    setAdding(true)
    try {
      const created = await apiFetch<Memory>('/memories', {
        method: 'POST',
        body: JSON.stringify({ content }),
      })
      setMemories((current) => [created, ...current])
      setDraft('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save that.')
    } finally {
      setAdding(false)
    }
  }

  async function update(id: string, patch: Partial<Pick<Memory, 'content' | 'enabled'>>) {
    const previous = memories
    setMemories((current) => current.map((m) => (m.id === id ? { ...m, ...patch } : m)))
    try {
      await apiFetch<Memory>(`/memories/${id}`, {
        method: 'PATCH',
        body: JSON.stringify(patch),
      })
    } catch (err) {
      setMemories(previous)
      setError(err instanceof Error ? err.message : 'Could not save that change.')
    }
  }

  async function remove(id: string) {
    const previous = memories
    setMemories((current) => current.filter((m) => m.id !== id))
    try {
      await apiFetch<void>(`/memories/${id}`, { method: 'DELETE' })
    } catch {
      setMemories(previous)
    }
  }

  const active = memories.filter((m) => m.enabled).length

  return (
    <main className="mx-auto min-h-dvh w-full max-w-2xl px-6 py-10">
      <Link
        to="/"
        className="mb-8 inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" aria-hidden />
        Back to chat
      </Link>

      <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>

      <ThemeCard />

      <Card className="mt-6 p-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="inline-flex items-center gap-2 font-medium">
              <Brain className="size-4 text-primary" aria-hidden />
              Memory
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Facts included in every conversation. Pelita adds some as you talk; you can
              add, edit, switch off or delete any of them.
            </p>
          </div>
          <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
            {active}/{limit}
          </span>
        </div>

        <form onSubmit={add} className="mt-5 flex gap-2">
          <Input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Remember that…"
            maxLength={500}
            aria-label="New memory"
          />
          <Button type="submit" loading={adding} disabled={!draft.trim()}>
            <Plus className="size-4" aria-hidden />
            Add
          </Button>
        </form>

        {error && <Alert className="mt-4">{error}</Alert>}

        <div className="mt-5">
          {loading ? (
            <div className="grid place-items-center py-8">
              <Spinner />
            </div>
          ) : memories.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted-foreground">
              Nothing remembered yet.
            </p>
          ) : (
            <ul className="divide-y divide-border">
              {memories.map((memory) => (
                <MemoryRow
                  key={memory.id}
                  memory={memory}
                  onUpdate={update}
                  onDelete={remove}
                />
              ))}
            </ul>
          )}
        </div>
      </Card>
    </main>
  )
}

function MemoryRow({
  memory,
  onUpdate,
  onDelete,
}: {
  memory: Memory
  onUpdate: (id: string, patch: Partial<Pick<Memory, 'content' | 'enabled'>>) => void
  onDelete: (id: string) => void
}) {
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(memory.content)

  function commit() {
    const content = text.trim()
    if (content && content !== memory.content) onUpdate(memory.id, { content })
    setEditing(false)
  }

  return (
    <li className="group/memory flex items-start gap-3 py-3">
      <input
        type="checkbox"
        checked={memory.enabled}
        onChange={(e) => onUpdate(memory.id, { enabled: e.target.checked })}
        aria-label={memory.enabled ? 'Stop using this memory' : 'Use this memory'}
        className="mt-1 size-4 shrink-0 accent-[hsl(var(--primary))]"
      />

      <div className="min-w-0 flex-1">
        {editing ? (
          <div className="flex items-center gap-1">
            <Input
              autoFocus
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') commit()
                if (e.key === 'Escape') {
                  setText(memory.content)
                  setEditing(false)
                }
              }}
              maxLength={500}
              aria-label="Edit memory"
              className="h-8"
            />
            <Button variant="ghost" size="icon" onClick={commit} aria-label="Save">
              <Check className="size-3.5" aria-hidden />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => {
                setText(memory.content)
                setEditing(false)
              }}
              aria-label="Cancel"
            >
              <X className="size-3.5" aria-hidden />
            </Button>
          </div>
        ) : (
          <>
            <p className={cn('text-sm', !memory.enabled && 'text-muted-foreground line-through')}>
              {memory.content}
            </p>
            <span className="mt-0.5 text-xs text-muted-foreground">
              {memory.source === 'extracted' ? 'Added by Pelita' : 'Added by you'}
            </span>
          </>
        )}
      </div>

      {!editing && (
        <div className="reveal-on-hover flex shrink-0 gap-0.5 opacity-0 transition-opacity group-hover/memory:opacity-100 focus-within:opacity-100">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setEditing(true)}
            aria-label={`Edit: ${memory.content}`}
          >
            <Pencil className="size-3.5" aria-hidden />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => onDelete(memory.id)}
            aria-label={`Delete: ${memory.content}`}
            className="text-muted-foreground hover:text-destructive"
          >
            <Trash2 className="size-3.5" aria-hidden />
          </Button>
        </div>
      )}
    </li>
  )
}


const THEMES: { value: ThemeChoice; label: string; Icon: typeof Sun }[] = [
  { value: 'light', label: 'Light', Icon: Sun },
  { value: 'dark', label: 'Dark', Icon: Moon },
  { value: 'system', label: 'System', Icon: Monitor },
]

function ThemeCard() {
  const { choice, setChoice } = useTheme()

  return (
    <Card className="mt-8 p-6">
      <h2 className="font-medium">Appearance</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        Every colour comes from one file, so a fork can restyle the whole app by editing
        <code className="mx-1 rounded bg-muted px-1 py-0.5 text-xs">theme.css</code>.
      </p>

      <div
        role="radiogroup"
        aria-label="Theme"
        className="mt-4 inline-flex rounded-lg border border-border p-1"
      >
        {THEMES.map(({ value, label, Icon }) => (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={choice === value}
            onClick={() => setChoice(value)}
            className={cn(
              'inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition-colors',
              choice === value
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:bg-hover',
            )}
          >
            <Icon className="size-3.5" aria-hidden />
            {label}
          </button>
        ))}
      </div>
    </Card>
  )
}

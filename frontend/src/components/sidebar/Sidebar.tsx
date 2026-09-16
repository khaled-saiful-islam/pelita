import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Check, LogOut, MoreHorizontal, PenSquare, Settings, Trash2, X } from 'lucide-react'
import { Button, Spinner } from '@/components/ui'
import { cn } from '@/lib/utils'
import { useAuth } from '@/lib/auth'
import type { ConversationSummary } from '@/hooks/useConversations'

/** Buckets by recency, the way every chat sidebar people already know does. */
export function groupByRecency(
  conversations: ConversationSummary[],
  now: Date = new Date(),
): [string, ConversationSummary[]][] {
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const day = 86_400_000

  const buckets: Record<string, ConversationSummary[]> = {
    Today: [],
    Yesterday: [],
    'Previous 7 days': [],
    'Previous 30 days': [],
    Older: [],
  }

  for (const conversation of conversations) {
    const at = new Date(conversation.updated_at).getTime()
    if (at >= startOfToday) buckets.Today.push(conversation)
    else if (at >= startOfToday - day) buckets.Yesterday.push(conversation)
    else if (at >= startOfToday - 7 * day) buckets['Previous 7 days'].push(conversation)
    else if (at >= startOfToday - 30 * day) buckets['Previous 30 days'].push(conversation)
    else buckets.Older.push(conversation)
  }

  return Object.entries(buckets).filter(([, items]) => items.length > 0)
}

export function Sidebar({
  conversations,
  activeId,
  loading,
  onSelect,
  onNew,
  onRename,
  onDelete,
}: {
  conversations: ConversationSummary[]
  activeId: string | null
  loading: boolean
  onSelect: (id: string) => void
  onNew: () => void
  onRename: (id: string, title: string) => void
  onDelete: (id: string) => void
}) {
  const { user, signOut } = useAuth()
  const groups = groupByRecency(conversations)

  return (
    <aside className="flex h-dvh w-[var(--sidebar-width)] shrink-0 flex-col border-r border-border bg-sidebar">
      <div className="p-3">
        <button
          type="button"
          onClick={onNew}
          className={cn(
            'flex w-full items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2',
            'text-sm font-medium shadow-sm transition-colors hover:bg-muted',
          )}
        >
          <PenSquare className="size-4" aria-hidden />
          New chat
        </button>
      </div>

      <nav className="flex-1 overflow-y-auto px-2 pb-2" aria-label="Conversation history">
        {loading && conversations.length === 0 && (
          <div className="grid place-items-center py-8">
            <Spinner />
          </div>
        )}

        {!loading && conversations.length === 0 && (
          <p className="px-3 py-8 text-center text-sm text-muted-foreground">
            No conversations yet.
          </p>
        )}

        {groups.map(([label, items]) => (
          <div key={label} className="mb-3">
            <h2 className="px-3 py-1.5 text-xs font-medium text-muted-foreground">{label}</h2>
            <ul className="space-y-0.5">
              {items.map((conversation) => (
                <ConversationRow
                  key={conversation.id}
                  conversation={conversation}
                  active={conversation.id === activeId}
                  onSelect={onSelect}
                  onRename={onRename}
                  onDelete={onDelete}
                />
              ))}
            </ul>
          </div>
        ))}
      </nav>

      <div className="border-t border-border p-2">
        <div className="flex items-center gap-1">
          <Link to="/profile" className="min-w-0 flex-1">
            <Button variant="ghost" size="sm" className="w-full justify-start truncate">
              <Settings className="size-4 shrink-0" aria-hidden />
              <span className="truncate">{user?.display_name ?? user?.username}</span>
            </Button>
          </Link>
          <Button variant="ghost" size="icon" onClick={signOut} aria-label="Sign out">
            <LogOut className="size-4" aria-hidden />
          </Button>
        </div>
      </div>
    </aside>
  )
}

function ConversationRow({
  conversation,
  active,
  onSelect,
  onRename,
  onDelete,
}: {
  conversation: ConversationSummary
  active: boolean
  onSelect: (id: string) => void
  onRename: (id: string, title: string) => void
  onDelete: (id: string) => void
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(conversation.title)
  const [menuOpen, setMenuOpen] = useState(false)

  function commit() {
    const title = draft.trim()
    if (title && title !== conversation.title) onRename(conversation.id, title)
    setEditing(false)
  }

  if (editing) {
    return (
      <li className="flex items-center gap-1 rounded-lg bg-surface px-2 py-1">
        <input
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') commit()
            if (e.key === 'Escape') setEditing(false)
          }}
          aria-label="Conversation title"
          className="min-w-0 flex-1 bg-transparent text-sm focus:outline-none"
        />
        <button type="button" onClick={commit} aria-label="Save title" className="p-1">
          <Check className="size-3.5" aria-hidden />
        </button>
        <button
          type="button"
          onClick={() => setEditing(false)}
          aria-label="Cancel rename"
          className="p-1"
        >
          <X className="size-3.5" aria-hidden />
        </button>
      </li>
    )
  }

  return (
    <li className="group/row relative">
      <button
        type="button"
        onClick={() => onSelect(conversation.id)}
        className={cn(
          'flex w-full items-center rounded-lg px-3 py-2 text-left text-sm transition-colors',
          active ? 'bg-surface font-medium shadow-sm' : 'hover:bg-muted',
        )}
      >
        <span className="truncate pr-6">{conversation.title}</span>
      </button>

      <button
        type="button"
        onClick={() => setMenuOpen((open) => !open)}
        aria-label={`Actions for ${conversation.title}`}
        aria-expanded={menuOpen}
        className={cn(
          'absolute right-1 top-1/2 -translate-y-1/2 rounded p-1 transition-opacity',
          'opacity-0 focus-visible:opacity-100 group-hover/row:opacity-100',
          menuOpen && 'opacity-100',
        )}
      >
        <MoreHorizontal className="size-4" aria-hidden />
      </button>

      {menuOpen && (
        <>
          {/* Click-away layer: a menu you cannot dismiss by clicking elsewhere
              is the kind of thing people notice immediately. */}
          <div className="fixed inset-0 z-10" onClick={() => setMenuOpen(false)} aria-hidden />
          <div className="absolute right-1 top-9 z-20 w-36 overflow-hidden rounded-lg border border-border bg-surface py-1 shadow-lg">
            <MenuItem
              onClick={() => {
                setDraft(conversation.title)
                setEditing(true)
                setMenuOpen(false)
              }}
            >
              <PenSquare className="size-3.5" aria-hidden />
              Rename
            </MenuItem>
            <MenuItem
              destructive
              onClick={() => {
                setMenuOpen(false)
                onDelete(conversation.id)
              }}
            >
              <Trash2 className="size-3.5" aria-hidden />
              Delete
            </MenuItem>
          </div>
        </>
      )}
    </li>
  )
}

function MenuItem({
  children,
  onClick,
  destructive,
}: {
  children: React.ReactNode
  onClick: () => void
  destructive?: boolean
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-muted',
        destructive && 'text-destructive',
      )}
    >
      {children}
    </button>
  )
}

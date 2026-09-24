import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Check,
  LogOut,
  MoreHorizontal,
  PanelLeftClose,
  PanelLeftOpen,
  PenSquare,
  Settings,
  Trash2,
  User,
  UserCog,
  X,
} from 'lucide-react'
import { useEffect } from 'react'
import { Button, Spinner } from '@/components/ui'
import { Confirm } from '@/components/ui/Confirm'
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
  open,
  onClose,
  onSelect,
  onNew,
  onRename,
  onDelete,
}: {
  conversations: ConversationSummary[]
  activeId: string | null
  loading: boolean
  /** Drawer state. Ignored from `md` up, where the sidebar is always present. */
  open: boolean
  onClose: () => void
  onSelect: (id: string) => void
  onNew: () => void
  onRename: (id: string, title: string) => void
  onDelete: (id: string) => void
}) {
  const { user, signOut } = useAuth()
  const groups = groupByRecency(conversations)
  // Held here rather than in the row, so the dialog is not inside the thing it
  // is about to remove.
  const [confirming, setConfirming] = useState<ConversationSummary | null>(null)
  // Folded to a rail of icons, from md up. On a phone the sidebar is a drawer
  // already, and folding a drawer would only hide the button that opens it.
  const [folded, setFolded] = useFolded()

  // Escape closes the drawer. Expected of anything that covers the page, and
  // the only way out for someone not using a pointer.
  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  return (
    <>
      {/* Scrim, mobile only. */}
      <div
        onClick={onClose}
        aria-hidden
        className={cn(
          'fixed inset-0 z-30 bg-foreground/20 backdrop-blur-[2px] transition-opacity md:hidden',
          open ? 'opacity-100' : 'pointer-events-none opacity-0',
        )}
      />

      <aside
        className={cn(
          'flex h-dvh w-[var(--sidebar-width)] shrink-0 flex-col overflow-hidden border-r border-border bg-sidebar',
          // Off-canvas below md, static from md up.
          'fixed inset-y-0 left-0 z-40 md:static md:translate-x-0',
          'transition-[transform,width] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)]',
          open ? 'translate-x-0 shadow-lg' : '-translate-x-full',
          folded && 'md:w-[3.75rem]',
        )}
      >
      {folded && (
        <Rail
          onUnfold={() => setFolded(false)}
          onNew={onNew}
          admin={!!user?.is_admin}
          onSignOut={signOut}
        />
      )}

      <div className={cn('flex items-center gap-1 p-3', folded && 'md:hidden')}>
        <button
          type="button"
          onClick={onNew}
          className={cn(
            'flex w-full items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2',
            'text-sm font-medium shadow-sm transition-colors hover:border-hover-border hover:bg-hover',
          )}
        >
          <PenSquare className="size-4" aria-hidden />
          New chat
        </button>

        <Button
          variant="ghost"
          size="icon"
          onClick={() => setFolded(true)}
          aria-label="Minimise the sidebar"
          title="Minimise the sidebar"
          className="hidden shrink-0 md:inline-flex"
        >
          <PanelLeftClose className="size-4" aria-hidden />
        </Button>

        <Button
          variant="ghost"
          size="icon"
          onClick={onClose}
          aria-label="Close menu"
          className="md:hidden"
        >
          <X className="size-4" aria-hidden />
        </Button>
      </div>

      <nav
        className={cn('flex-1 overflow-y-auto px-2 pb-2', folded && 'md:hidden')}
        aria-label="Conversation history"
      >
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
                  onDelete={() => setConfirming(conversation)}
                />
              ))}
            </ul>
          </div>
        ))}
      </nav>

      <div className={cn('border-t border-border p-2', folded && 'md:hidden')}>
        <div className="flex items-center gap-1">
          <Link to="/profile" className="min-w-0 flex-1">
            <Button variant="ghost" size="sm" className="w-full justify-start truncate">
              <User className="size-4 shrink-0" aria-hidden />
              <span className="truncate">{user?.display_name ?? user?.username}</span>
            </Button>
          </Link>
          {/* Only for admins — the route is guarded on the server too, so
              this is about not offering a door that will not open. */}
          {user?.is_admin && (
            <Link to="/admin">
              <Button variant="ghost" size="icon" aria-label="Users">
                <UserCog className="size-4" aria-hidden />
              </Button>
            </Link>
          )}
          <Link to="/settings">
            <Button variant="ghost" size="icon" aria-label="Settings">
              <Settings className="size-4" aria-hidden />
            </Button>
          </Link>
          <Button variant="ghost" size="icon" onClick={signOut} aria-label="Sign out">
            <LogOut className="size-4" aria-hidden />
          </Button>
        </div>
      </div>
      </aside>

      {/* Deleting a chat takes the messages, the files and anything made in it
          with it, and there is no undo. Naming it is the point: a dialog that
          only says "are you sure?" asks a question nobody can answer. */}
      {confirming && (
        <Confirm
          title="Delete this chat?"
          body={
            <>
              <span className="font-medium text-foreground">{confirming.title}</span> and
              everything in it — the messages, the files, anything it made — will be gone.
              This cannot be undone.
            </>
          }
          confirmLabel="Delete chat"
          onCancel={() => setConfirming(null)}
          onConfirm={() => {
            const doomed = confirming
            setConfirming(null)
            onDelete(doomed.id)
          }}
        />
      )}
    </>
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
  /** Chosen from the row's menu. What actually happens is asked about first. */
  onDelete: () => void
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
          'flex w-full items-center rounded-lg border px-3 py-2 text-left text-sm transition-colors',
          // The border is always there, transparent until it is wanted, so
          // nothing shifts by a pixel when the pointer arrives.
          active
            ? 'border-hover-border bg-selected font-medium'
            : 'border-transparent hover:border-hover-border hover:bg-hover',
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
          'reveal-on-hover absolute right-1 top-1/2 -translate-y-1/2 rounded p-1 transition-opacity',
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
                onDelete()
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
        'flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-hover',
        destructive && 'text-destructive',
      )}
    >
      {children}
    </button>
  )
}

const FOLDED_KEY = 'pelita-sidebar-folded'

/** Remembered, because a sidebar that springs back open on every reload is
 *  one somebody has to fold again every time. */
function useFolded(): [boolean, (folded: boolean) => void] {
  const [folded, setFolded] = useState(() => {
    try {
      return localStorage.getItem(FOLDED_KEY) === '1'
    } catch {
      return false
    }
  })
  const set = (next: boolean) => {
    setFolded(next)
    try {
      localStorage.setItem(FOLDED_KEY, next ? '1' : '0')
    } catch {
      // Private windows: it folds for this visit and forgets.
    }
  }
  return [folded, set]
}

/**
 * The sidebar folded down to what is needed without it: a way back, a new
 * chat, and the account. The conversation list is the part that takes room,
 * and it is one click away.
 */
function Rail({
  onUnfold,
  onNew,
  admin,
  onSignOut,
}: {
  onUnfold: () => void
  onNew: () => void
  admin: boolean
  onSignOut: () => void
}) {
  return (
    <div className="hidden h-full flex-col items-center gap-1 py-3 md:flex">
      <RailButton label="Open the sidebar" onClick={onUnfold}>
        <PanelLeftOpen className="size-4" aria-hidden />
      </RailButton>
      <RailButton label="New chat" onClick={onNew} strong>
        <PenSquare className="size-4" aria-hidden />
      </RailButton>

      <div className="mt-auto flex flex-col items-center gap-1">
        <Link to="/profile" aria-label="Profile" title="Profile">
          <RailButton label="Profile">
            <User className="size-4" aria-hidden />
          </RailButton>
        </Link>
        {admin && (
          <Link to="/admin" aria-label="Users" title="Users">
            <RailButton label="Users">
              <UserCog className="size-4" aria-hidden />
            </RailButton>
          </Link>
        )}
        <Link to="/settings" aria-label="Settings" title="Settings">
          <RailButton label="Settings">
            <Settings className="size-4" aria-hidden />
          </RailButton>
        </Link>
        <RailButton label="Sign out" onClick={onSignOut}>
          <LogOut className="size-4" aria-hidden />
        </RailButton>
      </div>
    </div>
  )
}

function RailButton({
  label,
  onClick,
  strong,
  children,
}: {
  label: string
  onClick?: () => void
  strong?: boolean
  children: React.ReactNode
}) {
  const Tag = onClick ? 'button' : 'span'
  return (
    <Tag
      {...(onClick ? { type: 'button' as const, onClick, 'aria-label': label } : {})}
      title={label}
      className={cn(
        'grid size-9 place-items-center rounded-lg transition-colors',
        strong
          ? 'border border-border bg-surface shadow-sm hover:border-hover-border hover:bg-hover'
          : 'text-muted-foreground hover:bg-hover hover:text-foreground',
      )}
    >
      {children}
    </Tag>
  )
}

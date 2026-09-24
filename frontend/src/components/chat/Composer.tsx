import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'
import { useRef as useNodeRef } from 'react'
import { ArrowUp, Check, Globe, Paperclip, Square } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { SearchMode } from '@/hooks/useChat'
import { acceptAttribute, type AttachedFile } from '@/hooks/useDocuments'
import { Attachments } from './Attachments'

const MAX_HEIGHT_PX = 224 // matches --composer-max-height in theme.css
const SEARCH_MODE_KEY = 'pelita-search-mode'

const MODES: { value: SearchMode; label: string; hint: string }[] = [
  { value: 'auto', label: 'Auto', hint: 'Search when the question needs current information' },
  { value: 'always', label: 'Always', hint: 'Search on every message' },
  { value: 'off', label: 'Off', hint: 'Never search' },
]

/** Persisted, because a preference that resets on reload is not a preference. */
function readMode(): SearchMode {
  try {
    const stored = localStorage.getItem(SEARCH_MODE_KEY)
    if (stored === 'auto' || stored === 'always' || stored === 'off') return stored
  } catch {
    // Private windows and blocked storage both throw.
  }
  return 'auto'
}

/** What the page can do to the box: put a request in it, ready to edit. */
export interface ComposerHandle {
  fill: (text: string, selection?: [number, number]) => void
}

export const Composer = forwardRef<ComposerHandle, ComposerProps>(function Composer(
  {
    onSend,
    onStop,
    streaming,
    disabled,
    searchEnabled,
    above,
    imagesEnabled = false,
    files,
    uploadingFile,
    atFileLimit,
    onAttach,
    onRemoveFile,
    placeholder = 'Message Pelita…',
    autoFocus,
  },
  ref,
) {
  const [value, setValue] = useState('')
  const [searchMode, setSearchMode] = useState<SearchMode>(readMode)
  const [menuOpen, setMenuOpen] = useState(false)
  const filePicker = useNodeRef<HTMLInputElement>(null)
  const textarea = useRef<HTMLTextAreaElement>(null)

  // Grow with the content up to a ceiling, then scroll inside.
  useEffect(() => {
    const el = textarea.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT_PX)}px`
  }, [value])

  function submit() {
    const text = value.trim()
    if (!text || streaming) return
    onSend(text, { searchMode: searchEnabled ? searchMode : 'off' })
    setValue('')
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends, Shift+Enter makes a new line. IME composition must not be
    // interrupted, or typing Chinese or Japanese sends half a word.
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      submit()
    }
  }

  // Picking a kind writes its request here with the subject selected, so the
  // next thing typed replaces the subject and keeps the request around it.
  useImperativeHandle(
    ref,
    () => ({
      fill(text, selection) {
        setValue(text)
        requestAnimationFrame(() => {
          const el = textarea.current
          if (!el) return
          el.focus()
          const [start, end] = selection ?? [text.length, text.length]
          el.setSelectionRange(start, end)
        })
      },
    }),
    [],
  )

  const canSend = value.trim().length > 0 && !streaming && !disabled

  return (
    <div
      className="sticky bottom-0 bg-gradient-to-t from-background via-background to-transparent pt-4"
      data-typing={value.trim().length > 0 ? 'true' : 'false'}
    >
      <div className="mx-auto w-full max-w-[var(--message-column)] px-4 pb-4">
        {above}
        <div
          className={cn(
            'rounded-2xl border border-input bg-surface p-2 shadow',
            'transition-shadow focus-within:ring-2 focus-within:ring-ring',
          )}
        >
        <Attachments files={files} uploading={uploadingFile} onRemove={onRemoveFile} />

        <div className="flex items-end gap-2">
          <textarea
            ref={textarea}
            rows={1}
            value={value}
            autoFocus={autoFocus}
            disabled={disabled}
            placeholder={placeholder}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={onKeyDown}
            aria-label="Message"
            className={cn(
              'flex-1 resize-none bg-transparent px-2 py-2 text-sm leading-relaxed',
              'placeholder:text-muted-foreground focus:outline-none disabled:opacity-50',
            )}
          />

          {streaming ? (
            <button
              type="button"
              onClick={onStop}
              aria-label="Stop generating"
              title="Stop generating"
              className={cn(
                'grid size-9 shrink-0 place-items-center rounded-xl',
                'bg-foreground text-background transition-opacity hover:opacity-80',
              )}
            >
              <Square className="size-3.5 fill-current" aria-hidden />
            </button>
          ) : (
            <button
              type="button"
              onClick={submit}
              disabled={!canSend}
              aria-label="Send message"
              className={cn(
                'grid size-9 shrink-0 place-items-center rounded-xl transition-colors',
                canSend
                  ? 'bg-primary text-primary-foreground hover:bg-accent-600'
                  : 'bg-muted text-muted-foreground',
              )}
            >
              <ArrowUp className="size-4" aria-hidden />
            </button>
          )}
        </div>

        <div className="relative flex items-center gap-1 px-1 pt-1.5">
          <input
            ref={filePicker}
            type="file"
            accept={acceptAttribute(imagesEnabled)}
            className="hidden"
            onChange={(event) => {
              const chosen = event.target.files?.[0]
              if (chosen) onAttach(chosen)
              // Reset so picking the same file twice still fires a change.
              event.target.value = ''
            }}
          />
          <button
            type="button"
            onClick={() => filePicker.current?.click()}
            disabled={atFileLimit || Boolean(uploadingFile)}
            title={
              atFileLimit
                ? 'This chat has reached its file limit'
                : 'Attach a file (text, Markdown, CSV, JSON, PDF or Word)'
            }
            aria-label="Attach a file"
            className={cn(
              'inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs font-medium transition-colors',
              atFileLimit || uploadingFile
                ? 'cursor-not-allowed text-muted-foreground/50'
                : 'text-muted-foreground hover:bg-hover',
            )}
          >
            <Paperclip className="size-3.5" aria-hidden />
            Attach
          </button>

          <button
            type="button"
            onClick={() => setMenuOpen((open) => !open)}
            disabled={!searchEnabled}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            title={
              searchEnabled
                ? MODES.find((m) => m.value === searchMode)?.hint
                : 'Set SERPAPI_KEY in .env to enable web search'
            }
            className={cn(
              'inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs font-medium transition-colors',
              !searchEnabled && 'cursor-not-allowed text-muted-foreground/50',
              searchEnabled && searchMode === 'always' && 'bg-accent-100 text-accent-800',
              searchEnabled && searchMode === 'auto' && 'text-muted-foreground hover:bg-hover',
              searchEnabled && searchMode === 'off' && 'text-muted-foreground/60 hover:bg-hover',
            )}
          >
            <Globe className="size-3.5" aria-hidden />
            Search
            <span className="opacity-70">
              {MODES.find((m) => m.value === searchMode)?.label}
            </span>
          </button>

          {menuOpen && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setMenuOpen(false)} aria-hidden />
              <div
                role="menu"
                className="absolute bottom-8 left-0 z-20 w-64 overflow-hidden rounded-lg border border-border bg-surface py-1 shadow-lg"
              >
                {MODES.map((mode) => (
                  <button
                    key={mode.value}
                    type="button"
                    role="menuitemradio"
                    aria-checked={searchMode === mode.value}
                    onClick={() => {
                      setSearchMode(mode.value)
                      try {
                        localStorage.setItem(SEARCH_MODE_KEY, mode.value)
                      } catch {
                        // Applies this session even if it cannot be stored.
                      }
                      setMenuOpen(false)
                    }}
                    className="flex w-full items-start gap-2 px-3 py-2 text-left hover:bg-hover"
                  >
                    <Check
                      className={cn(
                        'mt-0.5 size-3.5 shrink-0',
                        searchMode === mode.value ? 'text-primary' : 'opacity-0',
                      )}
                      aria-hidden
                    />
                    <span>
                      <span className="block text-sm font-medium">{mode.label}</span>
                      <span className="block text-xs text-muted-foreground">{mode.hint}</span>
                    </span>
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
        </div>

        <p className="mt-2 text-center text-xs text-muted-foreground">
          Pelita can make mistakes. Check important information.
        </p>
      </div>
    </div>
  )
})

interface ComposerProps {
  onSend: (text: string, options: { searchMode: SearchMode }) => void
  onStop: () => void
  streaming: boolean
  disabled?: boolean
  /** False when SERPAPI_KEY is unset; the toggle is shown but not usable. */
  searchEnabled: boolean
  /** Shown directly above the box, inside the same sticky strip: what can be
   *  made, on the new-chat screen and in a conversation. */
  above?: React.ReactNode
  /** Whether the picker offers images, which needs a vision model. */
  imagesEnabled?: boolean
  files: AttachedFile[]
  uploadingFile: string | null
  atFileLimit: boolean
  onAttach: (file: File) => void
  onRemoveFile: (id: string) => void
  placeholder?: string
  autoFocus?: boolean
}

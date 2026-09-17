import { useEffect, useRef, useState } from 'react'
import { ArrowUp, Globe, Square } from 'lucide-react'
import { cn } from '@/lib/utils'

const MAX_HEIGHT_PX = 224 // matches --composer-max-height in theme.css

export function Composer({
  onSend,
  onStop,
  streaming,
  disabled,
  searchEnabled,
  placeholder = 'Message Pelita…',
  autoFocus,
}: {
  onSend: (text: string, options: { useSearch: boolean }) => void
  onStop: () => void
  streaming: boolean
  disabled?: boolean
  /** False when SERPAPI_KEY is unset; the toggle is shown but not usable. */
  searchEnabled: boolean
  placeholder?: string
  autoFocus?: boolean
}) {
  const [value, setValue] = useState('')
  const [useSearch, setUseSearch] = useState(false)
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
    onSend(text, { useSearch: useSearch && searchEnabled })
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

  const canSend = value.trim().length > 0 && !streaming && !disabled

  return (
    <div className="sticky bottom-0 bg-gradient-to-t from-background via-background to-transparent pt-4">
      <div className="mx-auto w-full max-w-[var(--message-column)] px-4 pb-4">
        <div
          className={cn(
            'rounded-2xl border border-input bg-surface p-2 shadow',
            'transition-shadow focus-within:ring-2 focus-within:ring-ring',
          )}
        >
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

        <div className="flex items-center gap-1 px-1 pt-1.5">
          <button
            type="button"
            onClick={() => setUseSearch((on) => !on)}
            disabled={!searchEnabled}
            aria-pressed={useSearch && searchEnabled}
            title={
              searchEnabled
                ? 'Search the web before answering'
                : 'Set SERPAPI_KEY in .env to enable web search'
            }
            className={cn(
              'inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs font-medium transition-colors',
              !searchEnabled && 'cursor-not-allowed text-muted-foreground/50',
              searchEnabled && useSearch && 'bg-accent-100 text-accent-800',
              searchEnabled && !useSearch && 'text-muted-foreground hover:bg-muted',
            )}
          >
            <Globe className="size-3.5" aria-hidden />
            Search
          </button>
        </div>
        </div>

        <p className="mt-2 text-center text-xs text-muted-foreground">
          Pelita can make mistakes. Check important information.
        </p>
      </div>
    </div>
  )
}

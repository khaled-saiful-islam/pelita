import { ShieldAlert } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { GuardAlert } from '@/hooks/useChat'

const SOURCE_LABELS: Record<string, string> = {
  user_input: 'your message',
  web_search: 'a search result',
  news: 'a news item',
  document: 'a document',
}

const RULE_LABELS: Record<string, string> = {
  instruction_override: 'tried to override the assistant’s instructions',
  instruction_reset: 'tried to reset the assistant’s instructions',
  role_hijack: 'tried to change the assistant’s role',
  system_prompt_exfiltration: 'asked for the system prompt',
  fake_delimiters: 'contained fake chat-template markers',
  invisible_characters: 'contained hidden characters',
  opaque_blob: 'contained a long encoded blob',
}

/**
 * Shown when a guard fires.
 *
 * Says what was found, where it came from, and quotes the evidence — a guard
 * that silently alters what the model sees is indistinguishable from a bug, and
 * a warning nobody can check is one people learn to dismiss.
 */
export function GuardBanner({ alerts }: { alerts: GuardAlert[] }) {
  if (alerts.length === 0) return null

  return (
    <div className="mb-3 space-y-2">
      {alerts.map((alert, index) => (
        <div
          key={`${alert.source}-${index}`}
          role="status"
          className={cn(
            'rounded-lg border px-3 py-2 text-xs',
            alert.severity === 'high'
              ? 'border-destructive/30 bg-destructive/10 text-destructive'
              : 'border-warning/30 bg-warning/10 text-warning',
          )}
        >
          <p className="flex items-start gap-1.5 font-medium">
            <ShieldAlert className="mt-px size-3.5 shrink-0" aria-hidden />
            <span>
              Prompt-injection guard: {SOURCE_LABELS[alert.source] ?? alert.source}{' '}
              {alert.rules.map((r) => RULE_LABELS[r] ?? r).join(', ')}.
            </span>
          </p>

          {alert.evidence && (
            <p className="mt-1 pl-5 font-mono opacity-80">“{alert.evidence}”</p>
          )}

          <p className="mt-1 pl-5 opacity-80">
            {alert.source === 'user_input'
              ? 'Your message was sent unchanged — this is only a notice.'
              : 'That text was marked as data, not instructions, before the model saw it.'}
          </p>
        </div>
      ))}
    </div>
  )
}

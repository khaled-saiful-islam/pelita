import { Check, Loader2 } from 'lucide-react'
import type { ArtifactBuild } from '@/lib/chat-types'

/**
 * What is happening while an artifact is made.
 *
 * Every line here is a phase the build actually has. A progress display that
 * reports nothing real is a lie with a nicer appearance, and a minute of
 * silence is indistinguishable from a hang.
 */
export function BuildSteps({ build }: { build: ArtifactBuild }) {
  return (
    <ol className="space-y-2 text-sm" aria-live="polite">
      {build.steps.map((step, index) => {
        const current = index === build.steps.length - 1 && !build.failed
        return (
          <li key={`${step.label}-${index}`} className="flex items-start gap-2">
            {current ? (
              <Loader2 className="mt-0.5 size-3.5 shrink-0 animate-spin text-primary" aria-hidden />
            ) : (
              <Check className="mt-0.5 size-3.5 shrink-0 text-success" aria-hidden />
            )}
            <span className="min-w-0">
              <span className={current ? 'shimmer' : 'text-muted-foreground'}>{step.label}</span>
              {step.detail && (
                <span className="ml-1 break-words text-muted-foreground">· {step.detail}</span>
              )}
            </span>
          </li>
        )
      })}
    </ol>
  )
}

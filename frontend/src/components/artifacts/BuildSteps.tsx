import { useEffect, useState } from 'react'
import { Check, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ArtifactBuild } from '@/lib/chat-types'

/**
 * What is happening while an artifact is made.
 *
 * Every line is a phase the build actually has, and the line still running
 * says how much has been written and for how long. A minute of silence under a
 * finished-looking tick is indistinguishable from a hang, which is the single
 * thing this display exists to prevent.
 */
export function BuildSteps({ build }: { build: ArtifactBuild }) {
  const elapsed = useElapsed(!build.failed)
  const steps = build.steps
  const current = steps.length - 1

  return (
    <div>
      <div className="mb-4 flex items-baseline justify-between">
        <h3 className="text-sm font-medium">
          {build.failed ? 'Could not finish' : 'Designing'}
        </h3>
        <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
          {elapsed}s
        </span>
      </div>

      <ol className="space-y-2.5 text-sm" aria-live="polite">
        {steps.map((step, index) => {
          const running = index === current && !build.failed
          return (
            <li key={`${step.label}-${index}`} className="flex items-start gap-2.5">
              <span className="mt-0.5 flex size-4 shrink-0 items-center justify-center">
                {running ? (
                  <Loader2 className="size-3.5 animate-spin text-primary" aria-hidden />
                ) : (
                  <Check className="size-3.5 text-success" aria-hidden />
                )}
              </span>
              <span className="min-w-0">
                <span className={cn(running ? 'shimmer' : 'text-muted-foreground')}>
                  {step.label}
                </span>
                {step.detail && (
                  <span className="ml-1.5 break-words text-muted-foreground">{step.detail}</span>
                )}
              </span>
            </li>
          )
        })}
      </ol>

      {!build.failed && (
        <p className="mt-4 text-xs text-muted-foreground">
          A poster takes a minute or so. It is being designed, not filled into a template.
        </p>
      )}
    </div>
  )
}

/** Seconds since this build started, so a slow step is visibly slow rather
 *  than silently stuck. */
function useElapsed(running: boolean): number {
  const [seconds, setSeconds] = useState(0)
  useEffect(() => {
    if (!running) return
    const started = Date.now()
    const timer = setInterval(() => setSeconds(Math.round((Date.now() - started) / 1000)), 1000)
    return () => clearInterval(timer)
  }, [running])
  return seconds
}

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
const PATIENCE: Record<string, string> = {
  poster: 'A poster takes a minute or so. It is being designed, not filled into a template.',
  slides: 'A deck takes a couple of minutes. Every slide is written on its own.',
  games: 'A game takes a couple of minutes. It is played in a browser before you see it.',
  website:
    'A website takes a few minutes. Every page is written on its own, then opened on a desktop and a phone before you see it.',
  app: 'An app takes a couple of minutes. It is used in a browser — typed into, its buttons pressed — before you see it.',
}

export function BuildSteps({ build }: { build: ArtifactBuild }) {
  const elapsed = useElapsed(!build.failed)
  const steps = build.steps
  // A deck reports every slide as it lands and shows them below, so the list
  // above only needs the last few lines rather than all fourteen.
  const shown = build.kind === 'slides' ? steps.slice(-4) : steps

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
        {shown.map((step, index) => {
          const running = index === shown.length - 1 && !build.failed
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
          {PATIENCE[build.kind] ?? 'This is being made, not filled into a template.'}
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

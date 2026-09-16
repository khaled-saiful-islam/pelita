import { cn } from '@/lib/utils'

/**
 * The Pelita mark.
 *
 * Inline rather than an <img> so it inherits `currentColor` where that reads
 * better — muted in the sidebar, accent on the sign-in screen — without
 * shipping a second file per colour.
 */
export function Logo({ className, accent = true }: { className?: string; accent?: boolean }) {
  return (
    <svg
      viewBox="0 0 32 32"
      aria-hidden
      className={cn('shrink-0', accent && 'text-primary', className)}
      fill="none"
    >
      <path
        d="M16 1.5c1.6 8 6.9 13.3 14.9 14.9-8 1.6-13.3 6.9-14.9 14.9C14.4 23.3 9.1 18 1.1 16.4 9.1 14.8 14.4 9.5 16 1.5Z"
        fill="currentColor"
      />
    </svg>
  )
}

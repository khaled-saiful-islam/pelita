import { Monitor, Smartphone, Tablet } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { DEVICES, type Device, type SitePage } from '@/lib/site'
import { cn } from '@/lib/utils'

const GLYPHS: Record<Device, LucideIcon> = {
  desktop: Monitor,
  tablet: Tablet,
  phone: Smartphone,
}

/**
 * The strip above a website: which page, and which screen.
 *
 * The pages are the site's own nav, repeated where the panel can reach it —
 * the site's is inside a frame the panel cannot touch, and while editing its
 * links are switched off so a menu label can be clicked into and fixed. The
 * screens are the three widths a site is judged at, because "does it work on
 * a phone" is the first question anybody asks of one.
 */
export function SiteBar({
  pages,
  page,
  onPage,
  device,
  onDevice,
  actions,
  fit = false,
}: {
  pages: SitePage[]
  page: string | null
  onPage: (slug: string) => void
  device: Device
  onDevice: (device: Device) => void
  /** Anything the kind needs beside the screens: an app's "start over". */
  actions?: React.ReactNode
  /** On a desktop, laid out at the panel's width rather than a desktop's. */
  fit?: boolean
}) {
  const current = page ?? pages[0]?.slug ?? null

  return (
    <div className="flex h-10 shrink-0 items-center gap-2 border-b border-border bg-background/60 px-2 sm:px-3">
      {pages.length === 0 && <div className="min-w-0 flex-1" />}
      {pages.length > 0 && (
      <nav
        aria-label="Pages of this site"
        className="flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto [scrollbar-width:none]"
      >
        {pages.length > 1 &&
          pages.map((each) => (
            <button
              key={each.slug}
              type="button"
              onClick={() => onPage(each.slug)}
              aria-current={each.slug === current ? 'page' : undefined}
              className={cn(
                'shrink-0 rounded-md px-2.5 py-1 text-xs transition-colors',
                each.slug === current
                  ? 'bg-kind-website/15 font-medium text-kind-website'
                  : 'text-muted-foreground hover:bg-hover hover:text-foreground',
              )}
            >
              {each.title}
            </button>
          ))}
        {pages.length === 1 && (
          <span className="px-1 text-xs text-muted-foreground">One page</span>
        )}
      </nav>
      )}

      {actions}

      <div role="radiogroup" aria-label="Screen size" className="flex shrink-0 rounded-md bg-muted p-0.5">
        {(Object.keys(DEVICES) as Device[]).map((each) => {
          const Glyph = GLYPHS[each]
          return (
            <button
              key={each}
              type="button"
              role="radio"
              aria-checked={each === device}
              onClick={() => onDevice(each)}
              title={
                fit && each === 'desktop'
                  ? 'Desktop · as wide as the panel'
                  : `${DEVICES[each].label} · ${DEVICES[each].width}px`
              }
              className={cn(
                'flex items-center gap-1 rounded px-2 py-1 text-xs transition-colors',
                each === device
                  ? 'bg-background text-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground',
              )}
            >
              <Glyph className="size-3.5" aria-hidden />
              <span className="hidden xl:inline">{DEVICES[each].label}</span>
            </button>
          )
        })}
      </div>
    </div>
  )
}

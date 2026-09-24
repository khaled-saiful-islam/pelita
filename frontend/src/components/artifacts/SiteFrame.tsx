import { useEffect, useMemo, useRef, useState } from 'react'
import { EDITOR } from '@/components/artifacts/EditableFrame'
import { editableSite, siteLayout, type Device } from '@/lib/site'
import { cn } from '@/lib/utils'

/**
 * A website, in a frame that cannot reach the app.
 *
 * Every other kind is a fixed surface scaled to fit, because a poster you
 * scroll around is not a poster. A website is the opposite: it is meant to be
 * scrolled, and it changes shape with the screen it is on. So it fills the
 * panel's height and scrolls inside its own frame, and it is laid out at the
 * width of the device being looked at — a real desktop layout scaled down, or
 * a phone's at the phone's own size — rather than at whatever width the panel
 * happens to be, which is nobody's device.
 *
 * The frame's document is never touched from here. Which page is showing
 * comes back from the site's router as a message, and moving to another page
 * goes in as one; that is all that crosses the boundary.
 */
export function SiteFrame({
  html,
  sandbox,
  title,
  device,
  page,
  onPage,
  onEdit,
  onStore,
  fit = false,
}: {
  html: string
  sandbox: string
  title: string
  device: Device
  /** The page asked for from outside — the panel's page tabs. */
  page?: string | null
  /** Told whenever the site shows a page, however it got there. */
  onPage?: (slug: string) => void
  /** Present while editing: the words become editable and report changes. */
  onEdit?: (index: number, text: string) => void
  /** What an app asked to keep, as JSON text. */
  onStore?: (text: string) => void
  /** Laid out at the panel's own width on a desktop: an app is used here. */
  fit?: boolean
}) {
  const box = useRef<HTMLDivElement>(null)
  const frame = useRef<HTMLIFrameElement>(null)
  const shown = useRef<string | null>(null)
  const [room, setRoom] = useState({ width: 0, height: 0 })

  const editing = !!onEdit
  const document = useMemo(
    () => (editing ? editableSite(html, EDITOR) : html),
    [editing, html],
  )

  useEffect(() => {
    const element = box.current
    if (!element) return
    const measure = () => setRoom({ width: element.clientWidth, height: element.clientHeight })
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    const listen = (event: MessageEvent) => {
      // By frame, not by origin: an opaque origin reports itself as "null".
      if (event.source !== frame.current?.contentWindow) return
      const data = event.data as { source?: string; page?: string; index?: number; text?: string }
      if (data?.source === 'pelita-site' && data.page) {
        shown.current = data.page
        onPage?.(data.page)
      } else if (data?.source === 'pelita-edit' && typeof data.index === 'number') {
        onEdit?.(data.index, data.text ?? '')
      } else if (data?.source === 'pelita-store' && typeof (data as { data?: unknown }).data === 'string') {
        onStore?.((data as { data: string }).data)
      }
    }
    window.addEventListener('message', listen)
    return () => window.removeEventListener('message', listen)
  }, [onPage, onEdit, onStore])

  // Asked for a page the site is not already showing: say so.
  useEffect(() => {
    if (!page || page === shown.current) return
    frame.current?.contentWindow?.postMessage({ source: 'pelita-go', page }, '*')
  }, [page])

  // A new document starts wherever its address says, and will report it.
  useEffect(() => {
    shown.current = null
  }, [document])

  const handheld = device !== 'desktop'
  // A phone and a tablet sit inside a bezel, which takes its share of the room.
  const bezel = handheld ? 14 : 0
  const layout = siteLayout(device, Math.max(0, room.width - bezel), fit)
  const inner = Math.max(0, room.height - bezel)
  // Taller than the room by the scale, so that once shrunk it fills it.
  const height = layout.scale > 0 ? inner / layout.scale : 0

  return (
    <div className="flex min-h-0 flex-1 overflow-hidden p-3 sm:p-4">
      <div
        ref={box}
        className="flex min-h-0 min-w-0 flex-1 items-stretch justify-center"
      >
        <div
          className={cn(
            'shrink-0 overflow-hidden bg-background transition-[width] duration-300',
            handheld
              ? 'rounded-[26px] border-[7px] border-foreground/85 shadow-2xl'
              : 'rounded-lg shadow-lg ring-1 ring-border',
            editing && 'ring-2 ring-primary',
          )}
          style={{
            width: layout.width * layout.scale + bezel,
            height: inner + bezel,
            visibility: layout.scale > 0 ? 'visible' : 'hidden',
          }}
        >
          <iframe
            ref={frame}
            title={editing ? `${title} — editing` : title}
            srcDoc={document}
            // Never `allow-same-origin`: with scripts as well, the site could
            // reach straight back into the app. Editing needs scripts for the
            // editor and nothing else, so forms are left out of it.
            sandbox={editing ? 'allow-scripts' : sandbox}
            referrerPolicy="no-referrer"
            style={{
              width: layout.width,
              height,
              transform: `scale(${layout.scale})`,
              transformOrigin: 'top left',
              border: 0,
              display: 'block',
            }}
          />
        </div>
      </div>
    </div>
  )
}

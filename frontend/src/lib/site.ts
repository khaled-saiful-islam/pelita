/**
 * What the panel needs to know about a website, read from its document.
 *
 * A website is one file holding several `<section data-page>` elements, and the
 * router inside it decides which one shows. The panel cannot look inside the
 * frame — it has an opaque origin, which is the point — so it reads the pages
 * off the document it was given, and the router tells it by message which one
 * is on screen.
 */

export type Device = 'desktop' | 'tablet' | 'phone'

/** The widths a site is judged at. Desktop is what it was designed for first. */
export const DEVICES: Record<Device, { width: number; label: string }> = {
  desktop: { width: 1280, label: 'Desktop' },
  tablet: { width: 820, label: 'Tablet' },
  phone: { width: 390, label: 'Phone' },
}

export interface SitePage {
  slug: string
  title: string
}

const PAGE = /<section\b[^>]*\bdata-page\s*=\s*["']([^"']+)["'][^>]*>/gi
const TITLE = /\bdata-title\s*=\s*"([^"]*)"/i

export function isSite(kind: string | undefined): boolean {
  return kind === 'website'
}

export function isApp(kind: string | undefined): boolean {
  return kind === 'app'
}

/** Shown filling the panel and scrolling, rather than as a fixed surface. */
export function isFluid(kind: string | undefined): boolean {
  return isSite(kind) || isApp(kind)
}

/** The pages, in order, as the nav names them. */
export function sitePages(html: string): SitePage[] {
  const pages: SitePage[] = []
  const seen = new Set<string>()
  for (const match of html.matchAll(PAGE)) {
    const slug = match[1]
    if (seen.has(slug)) continue
    seen.add(slug)
    const title = TITLE.exec(match[0])?.[1] ?? slug
    pages.push({ slug, title: decode(title) })
  }
  return pages
}

/**
 * The width to lay the site out at, and how far to shrink it.
 *
 * A desktop site laid out at the panel's own width is its tablet layout, and
 * that is not what anybody asked to see. So it is laid out at a desktop width
 * and scaled down — unless the panel is wider than that, when it simply fills
 * it, the way a real browser window would.
 */
export function siteLayout(
  device: Device,
  room: number,
  fit = false,
): { width: number; scale: number } {
  const wanted = DEVICES[device].width
  if (room <= 0) return { width: wanted, scale: 0 }
  // An app is used in the panel, not looked at: shrunk to half size to show
  // its desktop layout, its buttons are too small to press. So on a desktop
  // it is laid out at the panel's own width, at full size.
  if (device === 'desktop' && (fit || room >= wanted)) return { width: room, scale: 1 }
  return { width: wanted, scale: Math.min(room / wanted, 1) }
}

/**
 * An app with what it last saved put in front of everything.
 *
 * Done here rather than stored, because the saved data belongs to a person and
 * the document belongs to the app. `null` is still written: it tells the app's
 * runtime not to go looking in a storage it cannot reach from inside a frame.
 */
export function withState(html: string, data: unknown): string {
  const given = JSON.stringify(data ?? null).replace(/</g, '\\u003c')
  const tag = `<script data-pelita="state">window.__PELITA_STATE__ = ${given};<\/script>`
  const head = /<head\b[^>]*>/i.exec(html)
  if (!head) return tag + html
  const at = head.index + head[0].length
  return html.slice(0, at) + tag + html.slice(at)
}

/**
 * The site made editable in place.
 *
 * Its own script is taken out: it can write into the page after load, and a
 * word it wrote is a word the server has never seen, so every number after it
 * would point at the wrong run. The routing stays, because a page that cannot
 * be reached cannot be edited — but links stop working, since clicking into a
 * menu label to fix it should not take you to another page. The panel's page
 * tabs move between pages instead.
 */
export function editableSite(html: string, editor: string): string {
  const without = html.replace(
    /<script\b(?![^>]*data-pelita)[^>]*>[\s\S]*?<\/script\s*>/gi,
    '',
  )
  const tag =
    `<script>document.addEventListener('click', function (event) {` +
    `if (event.target && event.target.closest && event.target.closest('a')) {` +
    `event.preventDefault(); event.stopImmediatePropagation(); }}, true);` +
    `${editor}<\/script>`
  // Before the router, so its listener is registered first and the router
  // never sees the click.
  const router = without.search(/<script\b[^>]*data-pelita\s*=\s*["']router["']/i)
  if (router !== -1) return without.slice(0, router) + tag + without.slice(router)
  return without.includes('</body>') ? without.replace('</body>', `${tag}</body>`) : without + tag
}

function decode(text: string): string {
  return text
    .replace(/&quot;/g, '"')
    .replace(/&#x27;|&#39;/g, "'")
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&amp;/g, '&')
}

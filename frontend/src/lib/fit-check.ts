/**
 * Measuring whether a poster actually fits, in a real browser.
 *
 * Static analysis of the document cannot answer this: whether a headline wraps
 * to three lines depends on the font that loaded, and that is only knowable
 * once it has. So the check happens here, before the finished artifact is
 * revealed.
 *
 * It runs in a throwaway frame with `allow-scripts` and no `allow-same-origin`,
 * carrying one script — this one, which we wrote. The document itself is
 * guaranteed script-free by the server's validator, and the frame is an opaque
 * origin regardless, so nothing in it can reach the app, its cookies or its
 * API.
 */

export interface FitProblem {
  tag: string
  text: string
  /** How far outside the canvas, in pixels. Zero when it is clipped by its own
   *  box rather than by the canvas. */
  outside: number
  selfClipped: boolean
}

export interface FitResult {
  fits: boolean
  problems: FitProblem[]
}

/** Runs inside the frame. Serialised, so it must not close over anything. */
const PROBE = `
// A poster has one surface; a deck has one per slide. Both are measured the
// same way, against whichever surface each element actually sits on.
const surfaces = document.querySelectorAll('.canvas, .slide')
const problems = []
for (const canvas of surfaces) {
  const box = canvas.getBoundingClientRect()
  for (const el of canvas.querySelectorAll('*')) {
    // Only elements with words of their own. A decorative full-bleed layer is
    // meant to run past the edge and be clipped, and counting it would report
    // every well-made poster as broken.
    const hasOwnText = Array.prototype.some.call(
      el.childNodes, (n) => n.nodeType === 3 && n.textContent.trim(),
    )
    if (!hasOwnText) continue
    const r = el.getBoundingClientRect()
    if (r.width === 0 && r.height === 0) continue
    const outside = Math.max(
      box.top - r.top, box.left - r.left, r.bottom - box.bottom, r.right - box.right,
    )
    const style = getComputedStyle(el)
    const selfClipped = style.overflow !== 'visible'
      && (el.scrollHeight - el.clientHeight > 1 || el.scrollWidth - el.clientWidth > 1)
    if (outside > 0.5 || selfClipped) {
      problems.push({
        tag: el.tagName.toLowerCase(),
        text: (el.textContent || '').trim().slice(0, 60),
        outside: outside > 0 ? Math.round(outside) : 0,
        selfClipped,
      })
    }
  }
}
parent.postMessage({ source: 'pelita-fit', problems }, '*')
`

/**
 * Wait for the document's fonts before measuring — a poster measured against
 * the fallback face is measured against the wrong one, and every result is
 * wrong in a way that looks convincing.
 */
function harness(html: string): string {
  const waiter =
    `<script>(function(){const run=function(){${PROBE}};` +
    `if(document.fonts&&document.fonts.ready){document.fonts.ready.then(function(){` +
    `requestAnimationFrame(run)})}else{setTimeout(run,300)}})()<\/script>`
  return html.includes('</body>')
    ? html.replace('</body>', `${waiter}</body>`)
    : html + waiter
}

export const FIT_TIMEOUT_MS = 4000

export function checkFit(html: string, timeout = FIT_TIMEOUT_MS): Promise<FitResult> {
  return new Promise((resolve) => {
    const frame = document.createElement('iframe')
    // Scripts, because measuring needs them. Never `allow-same-origin`: with
    // both, the frame could reach straight back into the app.
    frame.setAttribute('sandbox', 'allow-scripts')
    frame.setAttribute('aria-hidden', 'true')
    frame.style.cssText =
      'position:fixed;left:-10000px;top:0;width:3000px;height:3000px;border:0;visibility:hidden'

    let settled = false
    const finish = (result: FitResult) => {
      if (settled) return
      settled = true
      window.removeEventListener('message', onMessage)
      clearTimeout(timer)
      frame.remove()
      resolve(result)
    }

    const onMessage = (event: MessageEvent) => {
      // Identified by the frame it came from, not by origin: a sandboxed frame
      // without `allow-same-origin` has an opaque origin and reports "null".
      if (event.source !== frame.contentWindow) return
      const data = event.data as { source?: string; problems?: FitProblem[] }
      if (data?.source !== 'pelita-fit') return
      const problems = data.problems ?? []
      finish({ fits: problems.length === 0, problems })
    }

    // A frame that never answers must not hold the poster hostage. Assume it
    // fits and show it: a false alarm is worse than a missed one here, because
    // the person can see the result for themselves.
    const timer = setTimeout(() => finish({ fits: true, problems: [] }), timeout)

    window.addEventListener('message', onMessage)
    frame.srcdoc = harness(html)
    document.body.appendChild(frame)
  })
}

import { useEffect, useRef, useState } from 'react'
import { fitScale } from './fit-to-panel'

/** Used when an artifact arrived without a size of its own. A frame of zero by
 *  zero renders as nothing, which looks exactly like a failure. */
const FALLBACK = { width: 794, height: 1123 }

/**
 * The artifact itself, in a frame that cannot reach the app.
 *
 * `sandbox` comes from the kind rather than from this component, so the
 * preview and a shared page cannot end up disagreeing about what a document is
 * allowed to do. For a poster it is the empty string, which is the strongest
 * setting there is: an opaque origin with scripts, forms and navigation all
 * refused.
 *
 * The document is a fixed size and the panel is not, so it is scaled to fit
 * rather than scrolled. A poster you have to scroll around is not a poster.
 */
export function ArtifactFrame({
  html,
  width,
  height,
  sandbox,
  title,
}: {
  html: string
  width: number
  height: number
  sandbox: string
  title: string
}) {
  const box = useRef<HTMLDivElement>(null)
  const frame = useRef<HTMLIFrameElement>(null)
  const [scale, setScale] = useState(0)

  // A game only receives the arrow keys once its frame has focus, and an
  // iframe does not take focus by being visible. Without this the game is on
  // screen, drawn correctly and completely unresponsive: every key goes to the
  // page behind it. That reads, fairly, as the game being broken.
  //
  // Only for a kind that runs scripts. Taking focus for a poster would move it
  // off the message box for no reason.
  const playable = sandbox.includes('allow-scripts')
  useEffect(() => {
    if (!playable || scale <= 0) return
    // After the frame has laid out and loaded its document.
    const at = window.setTimeout(() => frame.current?.focus(), 150)
    return () => window.clearTimeout(at)
  }, [playable, scale, html])

  // A poster is whatever shape it decided to be — A4, a square, a wide banner —
  // and the panel is whatever width the window allows. Neither knows about the
  // other, so the size is always computed rather than assumed.
  const real = {
    width: width > 0 ? width : FALLBACK.width,
    height: height > 0 ? height : FALLBACK.height,
  }

  useEffect(() => {
    const element = box.current
    if (!element) return

    const fit = () => {
      // The element measured has no padding of its own, so this is the room
      // actually available. Measuring a padded box overflows by the padding.
      const available = element.clientWidth
      const room = element.clientHeight
      if (available <= 0 || room <= 0) return
      setScale(fitScale(real, { width: available, height: room }))
    }

    fit()
    const observer = new ResizeObserver(fit)
    observer.observe(element)
    return () => observer.disconnect()
  }, [real.width, real.height])

  return (
    <div className="flex min-h-0 flex-1 overflow-hidden p-4">
      <div
        ref={box}
        className="flex min-h-0 min-w-0 flex-1 items-center justify-center"
      >
      <div
        style={{
          width: real.width * scale,
          height: real.height * scale,
          // Hidden until measured rather than shown at full size and snapped
          // down, which reads as the panel breaking and then recovering.
          visibility: scale > 0 ? 'visible' : 'hidden',
        }}
        className="shrink-0 overflow-hidden rounded-md shadow-lg ring-1 ring-border"
      >
        <iframe
          ref={frame}
          title={title}
          srcDoc={html}
          // So a click anywhere in the game, or a tab to it, hands it the keys
          // back after focus has been somewhere else.
          onMouseEnter={playable ? () => frame.current?.focus() : undefined}
          sandbox={sandbox}
          referrerPolicy="no-referrer"
          style={{
            width: real.width,
            height: real.height,
            transform: `scale(${scale})`,
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

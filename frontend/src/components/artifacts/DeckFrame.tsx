import { useEffect, useRef, useState } from 'react'
import { fitScale } from './fit-to-panel'

/**
 * A deck, showing one slide at a time.
 *
 * The document is loaded once and moved, not reloaded per slide. Two reasons,
 * and the second one is not obvious: reloading flashes and refetches the fonts
 * every time somebody presses an arrow, and hiding the other slides with
 * `display: none` stops CSS counters incrementing — so every slide would be
 * numbered one.
 *
 * So the frame holds the whole deck at its full height and is translated
 * upwards by whole slides. Nothing reaches into it, which keeps a deck under
 * exactly the sandbox its kind declared.
 */
export function DeckFrame({
  html,
  width,
  height,
  count,
  current,
  sandbox,
  title,
}: {
  html: string
  width: number
  height: number
  count: number
  current: number
  sandbox: string
  title: string
}) {
  const box = useRef<HTMLDivElement>(null)
  const [scale, setScale] = useState(0)

  useEffect(() => {
    const element = box.current
    if (!element) return
    const fit = () =>
      setScale(
        fitScale({ width, height }, { width: element.clientWidth, height: element.clientHeight }),
      )
    fit()
    const observer = new ResizeObserver(fit)
    observer.observe(element)
    return () => observer.disconnect()
  }, [width, height])

  return (
    <div className="flex min-h-0 flex-1 overflow-hidden p-4">
      <div ref={box} className="flex min-h-0 min-w-0 flex-1 items-center justify-center">
        <div
          style={{
            width: width * scale,
            height: height * scale,
            visibility: scale > 0 ? 'visible' : 'hidden',
          }}
          className="relative shrink-0 overflow-hidden rounded-lg shadow-2xl ring-1 ring-border"
        >
          <iframe
            title={title}
            srcDoc={html}
            sandbox={sandbox}
            referrerPolicy="no-referrer"
            style={{
              width,
              // The whole deck, stacked. Moving it is what changes slide.
              height: height * Math.max(count, 1),
              transform: `scale(${scale}) translateY(${-current * height}px)`,
              transformOrigin: 'top left',
              transition: 'transform 380ms cubic-bezier(0.22, 1, 0.36, 1)',
              border: 0,
              display: 'block',
            }}
          />
        </div>
      </div>
    </div>
  )
}

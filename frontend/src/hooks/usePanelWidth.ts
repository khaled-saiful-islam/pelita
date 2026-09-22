import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * How wide the artifact panel is, and dragging it.
 *
 * A poster is the thing being looked at, so the panel starts as the larger
 * half. The width is remembered per browser, because someone who widens it
 * once means it.
 *
 * Bounds are a fraction of the window rather than pixels: the same drag should
 * behave the same on a laptop and on a wide monitor, and neither side may be
 * squeezed to nothing.
 */
const KEY = 'pelita.artifact-panel-width'
const DEFAULT_SHARE = 0.58
const MIN_SHARE = 0.3
const MAX_SHARE = 0.8
/** Below this the panel covers the conversation instead of sharing with it. */
export const OVERLAY_BELOW = 900

function clamp(share: number): number {
  return Math.min(MAX_SHARE, Math.max(MIN_SHARE, share))
}

function remembered(): number {
  try {
    const saved = Number(localStorage.getItem(KEY))
    return saved > 0 ? clamp(saved) : DEFAULT_SHARE
  } catch {
    // Private windows and blocked storage both land here. A default width is
    // a fine outcome; a panel that will not render is not.
    return DEFAULT_SHARE
  }
}

export function usePanelWidth() {
  const [share, setShare] = useState(DEFAULT_SHARE)
  const [dragging, setDragging] = useState(false)
  const [narrow, setNarrow] = useState(false)
  const latest = useRef(share)

  useEffect(() => {
    setShare(remembered())
    const measure = () => setNarrow(window.innerWidth < OVERLAY_BELOW)
    measure()
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [])

  useEffect(() => {
    if (!dragging) return

    const onMove = (event: PointerEvent) => {
      // Measured from the right edge: the panel is anchored there, so this is
      // the distance the pointer has opened up.
      const next = clamp((window.innerWidth - event.clientX) / window.innerWidth)
      latest.current = next
      setShare(next)
    }
    const stop = () => {
      setDragging(false)
      try {
        localStorage.setItem(KEY, String(latest.current))
      } catch {
        // Not worth a word on screen; the width simply is not remembered.
      }
    }

    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', stop)
    window.addEventListener('pointercancel', stop)
    // While dragging, the pointer is over an iframe half the time, and both of
    // these stop it selecting text or being swallowed by the frame.
    document.body.style.userSelect = 'none'
    document.body.style.cursor = 'col-resize'
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', stop)
      window.removeEventListener('pointercancel', stop)
      document.body.style.userSelect = ''
      document.body.style.cursor = ''
    }
  }, [dragging])

  const reset = useCallback(() => {
    latest.current = DEFAULT_SHARE
    setShare(DEFAULT_SHARE)
    try {
      localStorage.setItem(KEY, String(DEFAULT_SHARE))
    } catch {
      // As above.
    }
  }, [])

  return {
    width: narrow ? '100%' : `${(share * 100).toFixed(1)}%`,
    narrow,
    dragging,
    startDragging: () => setDragging(true),
    reset,
  }
}

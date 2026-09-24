/**
 * Picking a readable colour out of a palette.
 *
 * A palette arrives as a list, not as named roles, so "the second one is the
 * ink" is a guess — and on a deck whose first two colours were both cream it
 * put cream text on a cream card. Contrast is measurable, so it is measured.
 *
 * WCAG relative luminance, which is the same arithmetic every contrast checker
 * uses and is worth having exactly right.
 */

function channel(value: number): number {
  const v = value / 255
  return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4
}

export function luminance(hex: string): number {
  const cleaned = hex.replace('#', '')
  const full =
    cleaned.length === 3
      ? cleaned
          .split('')
          .map((c) => c + c)
          .join('')
      : cleaned
  const n = Number.parseInt(full.slice(0, 6), 16)
  if (!Number.isFinite(n)) return 0
  return (
    0.2126 * channel((n >> 16) & 255) +
    0.7152 * channel((n >> 8) & 255) +
    0.0722 * channel(n & 255)
  )
}

export function contrast(a: string, b: string): number {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (light + 0.05) / (dark + 0.05)
}

/** Whichever of these reads best on `background`, falling back to black or
 *  white when none of them does. */
export function readableOn(background: string, candidates: string[]): string {
  let best = ''
  let score = 0
  for (const candidate of candidates) {
    const ratio = contrast(background, candidate)
    if (ratio > score) {
      best = candidate
      score = ratio
    }
  }
  // 4.5:1 is the line below which small text stops being readable.
  if (score >= 4.5) return best
  return luminance(background) > 0.4 ? '#111111' : '#f5f5f5'
}

/**
 * The palette's accent: a colour of its own, but one that can be seen.
 *
 * "The first colour that is neither the ground nor the ink" put a pale sand
 * eyebrow on a pale paper card, where nobody could read it. The accent is now
 * the most visible of the remaining colours, and the ink when none of them
 * reaches 3:1 — the line for large and bold text, which is what an accent is
 * used for.
 */
export function accentOn(background: string, ink: string, palette: string[]): string {
  let best = ''
  let score = 0
  for (const colour of palette) {
    if (colour === background || colour === ink) continue
    const ratio = contrast(background, colour)
    if (ratio > score) {
      best = colour
      score = ratio
    }
  }
  return score >= 3 ? best : ink
}

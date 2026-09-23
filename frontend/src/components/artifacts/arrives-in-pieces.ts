/**
 * Whether an artifact arrives a piece at a time.
 *
 * Only a deck does. It reports each slide as it lands, so counting them off
 * against a plan is real progress.
 *
 * A game also names what is coming — its levels, through the same event a deck
 * uses for its slides — but it is written in one call, so there is nothing to
 * count. Shown as progress it produced "Writing slide 1 — Green Flag" during a
 * game build: a slide that is not a slide, counted towards a total that will
 * never be reached.
 */
export function arrivesInPieces(build: { kind: string; parts: unknown[] }): boolean {
  // Pieces already here settle it whatever the kind says; otherwise only a
  // deck promises them.
  return build.parts.length > 0 || build.kind === 'slides'
}

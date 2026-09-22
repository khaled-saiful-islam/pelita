/**
 * How much to shrink an artifact so it fits the room it has.
 *
 * Its own function so the rule is testable without a browser: a poster is
 * whatever shape it chose — A4, a square, a wide banner — and the panel is
 * whatever the window allows, so this is the one place the two meet.
 */
export function fitScale(
  artifact: { width: number; height: number },
  room: { width: number; height: number },
): number {
  if (room.width <= 0 || room.height <= 0) return 0
  const width = artifact.width > 0 ? artifact.width : 1
  const height = artifact.height > 0 ? artifact.height : 1
  // Never above 1. A poster blown up past its own size is a blurry poster.
  return Math.min(room.width / width, room.height / height, 1)
}

/**
 * A few pixels of what each kind makes, moving.
 *
 * Not an icon: a glyph says what a thing is called, and this says what it
 * does. A poster's sun comes up behind its headline, a deck deals its next
 * slide, a snake goes round its board, a website scrolls, an app is tapped.
 * Drawn in the tile's own colour (`currentColor`), out of plain elements, so
 * they cost nothing and scale with the tile.
 *
 * They only move while their tile is lit (see `MakeRail`); at rest each one
 * holds its first frame, which is drawn to be worth looking at on its own.
 */
export function Scene({ kind }: { kind: string }) {
  switch (kind) {
    case 'poster':
      return (
        <span className="scene scene-poster" aria-hidden>
          <span className="p-card">
            <span className="p-sun" />
            <span className="p-title" />
            <span className="p-line" />
            <span className="p-line p-short" />
          </span>
        </span>
      )
    case 'slides':
      return (
        <span className="scene scene-slides" aria-hidden>
          <span className="s-card s-back" />
          <span className="s-card s-middle" />
          <span className="s-card s-front">
            <span className="s-bar" />
            <span className="s-bar s-short" />
          </span>
        </span>
      )
    case 'games':
      return (
        <span className="scene scene-games" aria-hidden>
          <span className="g-board">
            <span className="g-food" />
            {[0, 1, 2, 3].map((segment) => (
              <span key={segment} className="g-segment" style={{ ['--segment' as string]: segment }} />
            ))}
          </span>
        </span>
      )
    case 'website':
      return (
        <span className="scene scene-website" aria-hidden>
          <span className="w-window">
            <span className="w-chrome">
              <i />
              <i />
              <i />
            </span>
            <span className="w-view">
              <span className="w-page">
                <span className="w-hero" />
                <span className="w-row">
                  <span />
                  <span />
                  <span />
                </span>
                <span className="w-text" />
                <span className="w-text w-short" />
                <span className="w-hero" />
              </span>
            </span>
          </span>
        </span>
      )
    case 'app':
      return (
        <span className="scene scene-app" aria-hidden>
          <span className="a-grid">
            {[0, 1, 2, 3, 4, 5].map((cell) => (
              <span key={cell} className="a-cell" style={{ ['--cell' as string]: cell }} />
            ))}
          </span>
        </span>
      )
    default:
      return (
        <span className="scene scene-other" aria-hidden>
          <span className="o-spark" />
        </span>
      )
  }
}

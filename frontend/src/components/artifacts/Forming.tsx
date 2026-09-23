import { useEffect } from 'react'
import type { ArtifactBuild } from '@/lib/chat-types'
import { readableOn } from '@/lib/contrast'

/**
 * The artifact, before it exists.
 *
 * A row of colour swatches is a fact about the artifact, not a picture of it —
 * it tells you a palette was chosen and nothing about what is being made. This
 * shows the thing instead: its real proportions, its real ground, its title set
 * in the face it has just chosen, and one sentence on what it will be. Light
 * moves across it, because something is happening.
 *
 * Nothing here is invented. Every value is one the artifact has already
 * committed to, which is why it is worth looking at: what is on screen while
 * you wait is the first true thing about what you are going to get.
 */
export function Forming({ build }: { build: ArtifactBuild }) {
  const design = build.design
  const ground = design?.palette?.[0] ?? '#1a1a1a'
  // By measured contrast, not by position. A palette is a list, not named
  // roles, and one whose first two colours were both cream put cream on cream.
  const ink = design ? readableOn(ground, design.palette.slice(1)) : '#ffffff'
  const accent =
    design?.palette?.find((colour) => colour !== ground && colour !== ink) ?? ink

  useFace(design?.display_font)

  // Its own shape. A poster is a portrait, a deck is widescreen, a game is
  // neither, and a square standing in for all three is a missed chance to say
  // which one you asked for.
  const ratio =
    build.width && build.height ? `${build.width} / ${build.height}` : '4 / 3'

  return (
    <div
      className="forming relative mx-auto w-full max-w-md overflow-hidden rounded-xl shadow-lg ring-1 ring-black/10"
      style={{ background: ground, color: ink, aspectRatio: ratio }}
      aria-hidden
    >
      <div className="flex h-full flex-col justify-between p-6">
        <span
          className="text-[10px] font-medium uppercase tracking-[0.18em] opacity-60"
          style={{ color: accent }}
        >
          {design?.movement || 'Choosing a direction'}
        </span>

        <div className="min-h-0">
          <h3
            className="forming-title text-2xl leading-tight sm:text-3xl"
            style={{ fontFamily: design?.display_font ? `"${design.display_font}", serif` : undefined }}
          >
            {build.title}
          </h3>
          {design?.rationale && (
            <p
              className="forming-line mt-2 line-clamp-3 text-xs leading-relaxed opacity-75"
              style={{ fontFamily: design.body_font ? `"${design.body_font}", sans-serif` : undefined }}
            >
              {design.rationale}
            </p>
          )}
        </div>

        <span className="text-[10px] opacity-50">
          {design ? `${design.display_font} · ${design.body_font}` : ''}
        </span>
      </div>

      {/* The light. Slow, diagonal, and the only thing here that is decoration
          rather than information — which is why it is the only thing here that
          is decoration. */}
      <span className="sheen" />
    </div>
  )
}

/**
 * Load the face the artifact chose, so the title is set in it rather than
 * described by name.
 *
 * Appended once per family and left in place: a build that changes its mind, or
 * a second artifact in the same conversation, should not re-request a font the
 * browser already has.
 */
function useFace(family?: string) {
  useEffect(() => {
    if (!family) return
    const href = `https://fonts.googleapis.com/css2?family=${encodeURIComponent(
      family,
    ).replace(/%20/g, '+')}:wght@400;600;700&display=swap`
    if (document.head.querySelector(`link[href="${CSS.escape(href)}"]`)) return
    const link = document.createElement('link')
    link.rel = 'stylesheet'
    link.href = href
    document.head.appendChild(link)
  }, [family])
}

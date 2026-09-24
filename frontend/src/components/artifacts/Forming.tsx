import { useEffect } from 'react'
import { colourOf, lookOf } from '@/components/artifacts/kind-look'
import type { ArtifactBuild } from '@/lib/chat-types'
import { accentOn, readableOn } from '@/lib/contrast'

/**
 * The artifact, before it exists.
 *
 * A row of colour swatches is a fact about the artifact, not a picture of it —
 * it tells you a palette was chosen and nothing about what is being made. This
 * shows the thing instead: its real proportions, its real ground, its title set
 * in the face it has just chosen, and one sentence on what it will be.
 *
 * It has three states because the build does, and they are the three that are
 * worth telling apart while you wait:
 *
 *   reading   — nothing has been decided. The card is dark and unmarked, and
 *               the space the writing will take is held open.
 *   designed  — the look arrives all at once. The ground, the ink and the two
 *               faces cross-fade in, which is the moment worth watching.
 *   making    — the document is being written. Same look, more light.
 *
 * Nothing here is invented. Every value is one the artifact has already
 * committed to, which is why it is worth looking at: what is on screen while
 * you wait is the first true thing about what you are going to get.
 */

type Phase = 'reading' | 'designed' | 'making'

/** The unlit card. Deliberately not grey — grey reads as broken. */
const UNLIT = '#15161c'

export function Forming({ build }: { build: ArtifactBuild }) {
  const design = build.design
  // A deck names its slides before it writes them; a poster and a game stream
  // the document itself. Either way, something is being written down.
  const writing =
    build.source.length > 0 || build.parts.length > 0 || (build.plan?.length ?? 0) > 0
  const phase: Phase = !design ? 'reading' : writing ? 'making' : 'designed'

  const kind = lookOf(build.kind)
  const ground = design?.palette?.[0] ?? UNLIT
  // By measured contrast, not by position. A palette is a list, not named
  // roles, and one whose first two colours were both cream put cream on cream.
  const ink = design ? readableOn(ground, design.palette.slice(1)) : '#ffffff'
  const accent = design ? accentOn(ground, ink, design.palette) : ink

  useFace(design?.display_font)

  // Its own shape. A poster is a portrait, a deck is widescreen, a game is
  // neither. Until the artifact has said, the kind's usual proportions are a
  // truer guess than a square — and the card reshaping when the design commits
  // to something else is the artifact telling you it decided.
  const ratio =
    build.width && build.height ? `${build.width} / ${build.height}` : kind.ratio

  return (
    <div
      className="forming-stage relative mx-auto w-full max-w-md"
      data-phase={phase}
      // Always the kind's own colour, the one its card and panel wear. Taken
      // from the palette instead, a design with a gold in it glowed in
      // Pelita's own amber, and every artifact looked like the app.
      style={{ ['--glow' as string]: colourOf(build.kind) }}
    >
      {/* The light it is being made under. Warm on purpose, and the one colour
          here that is not the artifact's own — it belongs to the workshop, not
          to the thing on the bench. */}
      <span className="forming-glow" aria-hidden />

      <div
        className="forming relative overflow-hidden rounded-xl shadow-lg ring-1 ring-black/10"
        style={{ background: ground, color: ink, aspectRatio: ratio }}
        aria-hidden
      >
        <div className="flex h-full flex-col justify-between p-6">
          <span
            className="text-[10px] font-medium uppercase tracking-[0.18em] opacity-60"
            style={{ color: accent }}
          >
            {design?.movement || 'Working out the look'}
          </span>

          <div className="min-h-0">
            <h3
              className="forming-title text-2xl leading-tight sm:text-3xl"
              style={{
                fontFamily: design?.display_font
                  ? `"${design.display_font}", serif`
                  : undefined,
              }}
            >
              {build.title}
            </h3>

            {design?.rationale ? (
              <p
                className="forming-line mt-2 line-clamp-3 text-xs leading-relaxed opacity-75"
                style={{
                  fontFamily: design.body_font ? `"${design.body_font}", sans-serif` : undefined,
                }}
              >
                {design.rationale}
              </p>
            ) : (
              // The space the sentence will take, held open so the card does
              // not jump when it arrives. Two rules, not a progress bar: they
              // say where the writing goes, and claim nothing about how far
              // along anything is.
              <div className="mt-3 space-y-2" aria-hidden>
                <span className="forming-rule block h-1.5 w-4/5 rounded-full" />
                <span className="forming-rule block h-1.5 w-2/5 rounded-full" />
              </div>
            )}
          </div>

          <span className="text-[10px] opacity-50">
            {design ? `${design.display_font} · ${design.body_font}` : ''}
          </span>
        </div>

        {/* Two, half a cycle apart, so the light never leaves the card. One
            band spends a third of its travel off the edge, and a card that
            goes still for a second reads as a card that has stopped. */}
        <span className="sheen" />
        <span className="sheen sheen--trailing" />
      </div>
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

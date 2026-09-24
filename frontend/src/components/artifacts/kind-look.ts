import { AppWindow, Gamepad2, Image as ImageIcon, LayoutGrid, Presentation, Sparkles } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

/**
 * How a kind of artifact presents itself in the transcript.
 *
 * A colour and a glyph, so three cards in one conversation are told apart
 * before they are read. Everything showed the same grey picture icon before,
 * which said only "an artifact" — the one thing you already knew.
 *
 * The classes are written out rather than built from the kind's name because
 * Tailwind reads them out of the source: `bg-kind-${kind}` compiles to
 * nothing at all, and the card would come out unstyled.
 *
 * Kinds come from a registry on the server and this list does not, so an
 * unknown one is expected rather than a bug: it gets the brand colour and a
 * neutral mark, and looks deliberate until someone gives it its own.
 */
export interface KindLook {
  icon: LucideIcon
  /** The glyph's own colour, for the states that do not sit on the solid tile. */
  colour: string
  /** The tile behind the glyph: the colour at full strength. */
  tile: string
  /** A wash across the whole card, kept faint enough to read on. */
  surface: string
  border: string
  /** What the card does under the pointer. */
  hover: string
  /** The ring on the card whose artifact is open in the panel. */
  ring: string
  /**
   * The shape this kind usually is, for the moments before the artifact has
   * chosen its own. A square standing in for a poster, a deck and a game says
   * none of them; the kind's own proportions are a true guess, and watching
   * the card reshape when the design commits to something else is worth
   * seeing.
   */
  ratio: string
}

const LOOKS: Record<string, KindLook> = {
  poster: {
    icon: ImageIcon,
    colour: 'text-kind-poster',
    tile: 'bg-kind-poster text-white',
    surface: 'bg-gradient-to-r from-kind-poster/12 to-kind-poster/[0.04]',
    border: 'border-kind-poster/30',
    hover: 'hover:border-kind-poster/60 hover:from-kind-poster/20 hover:to-kind-poster/[0.08]',
    ring: 'ring-kind-poster/50',
    ratio: '794 / 1123',
  },
  slides: {
    icon: Presentation,
    colour: 'text-kind-slides',
    tile: 'bg-kind-slides text-white',
    surface: 'bg-gradient-to-r from-kind-slides/12 to-kind-slides/[0.04]',
    border: 'border-kind-slides/30',
    hover: 'hover:border-kind-slides/60 hover:from-kind-slides/20 hover:to-kind-slides/[0.08]',
    ring: 'ring-kind-slides/50',
    ratio: '1600 / 900',
  },
  games: {
    icon: Gamepad2,
    colour: 'text-kind-games',
    tile: 'bg-kind-games text-white',
    surface: 'bg-gradient-to-r from-kind-games/12 to-kind-games/[0.04]',
    border: 'border-kind-games/30',
    hover: 'hover:border-kind-games/60 hover:from-kind-games/20 hover:to-kind-games/[0.08]',
    ring: 'ring-kind-games/50',
    ratio: '900 / 640',
  },
  website: {
    // A browser window, not a globe: the globe is web search's, on the search
    // button and on every search the assistant runs, and a website wearing it
    // read as one more search.
    icon: AppWindow,
    colour: 'text-kind-website',
    tile: 'bg-kind-website text-white',
    surface: 'bg-gradient-to-r from-kind-website/12 to-kind-website/[0.04]',
    border: 'border-kind-website/30',
    hover: 'hover:border-kind-website/60 hover:from-kind-website/20 hover:to-kind-website/[0.08]',
    ring: 'ring-kind-website/50',
    ratio: '1280 / 800',
  },
  app: {
    icon: LayoutGrid,
    colour: 'text-kind-app',
    tile: 'bg-kind-app text-white',
    surface: 'bg-gradient-to-r from-kind-app/12 to-kind-app/[0.04]',
    border: 'border-kind-app/30',
    hover: 'hover:border-kind-app/60 hover:from-kind-app/20 hover:to-kind-app/[0.08]',
    ring: 'ring-kind-app/50',
    ratio: '1280 / 800',
  },
}

const UNKNOWN: KindLook = {
  icon: Sparkles,
  colour: 'text-primary',
  tile: 'bg-primary text-primary-foreground',
  surface: 'bg-gradient-to-r from-primary/12 to-primary/[0.04]',
  border: 'border-primary/30',
  hover: 'hover:border-primary/60 hover:from-primary/20 hover:to-primary/[0.08]',
  ring: 'ring-primary/50',
  ratio: '4 / 3',
}

export function lookOf(kind: string | undefined): KindLook {
  return (kind && LOOKS[kind]) || UNKNOWN
}

/**
 * The kind's colour as a CSS value, for things lit through a custom property
 * rather than a class — a tile's glow, a scene's ink. Its theme token, so it
 * follows light and dark with everything else.
 */
export function colourOf(kind: string | undefined): string {
  return kind && LOOKS[kind] ? `hsl(var(--kind-${kind}))` : 'hsl(var(--primary))'
}

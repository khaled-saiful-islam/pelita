import { Gamepad2, Image as ImageIcon, Presentation, Sparkles } from 'lucide-react'
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
  },
  slides: {
    icon: Presentation,
    colour: 'text-kind-slides',
    tile: 'bg-kind-slides text-white',
    surface: 'bg-gradient-to-r from-kind-slides/12 to-kind-slides/[0.04]',
    border: 'border-kind-slides/30',
    hover: 'hover:border-kind-slides/60 hover:from-kind-slides/20 hover:to-kind-slides/[0.08]',
    ring: 'ring-kind-slides/50',
  },
  games: {
    icon: Gamepad2,
    colour: 'text-kind-games',
    tile: 'bg-kind-games text-white',
    surface: 'bg-gradient-to-r from-kind-games/12 to-kind-games/[0.04]',
    border: 'border-kind-games/30',
    hover: 'hover:border-kind-games/60 hover:from-kind-games/20 hover:to-kind-games/[0.08]',
    ring: 'ring-kind-games/50',
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
}

export function lookOf(kind: string | undefined): KindLook {
  return (kind && LOOKS[kind]) || UNKNOWN
}

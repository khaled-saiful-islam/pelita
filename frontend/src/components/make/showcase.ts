/**
 * What each kind of artifact is shown doing, to somebody deciding whether to
 * try it.
 *
 * A name and a glyph say what a thing is called. An example says what it is
 * *for* — "a night market in Ipoh, every Friday" is a poster somebody can
 * picture wanting, where "Poster" is only a word. So every kind carries a few,
 * written the way people here would actually ask, and the opening that turns
 * one into a request.
 *
 * Kinds come from the server's registry and this list does not, so a kind with
 * no entry still gets an opening built from its label rather than nothing.
 */

export interface Makeable {
  name: string
  label: string
  description: string
}

interface Showcase {
  /** Written into the box first; the example follows it. */
  opening: string
  examples: string[]
  /** One line on what it does, for the tile's tooltip. */
  promise: string
}

const SHOWCASE: Record<string, Showcase> = {
  poster: {
    opening: 'Design a poster for ',
    examples: [
      'a night market in Ipoh, every Friday 6pm',
      'a kopi festival in Penang this August',
      'a durian party at Bentong on Saturday',
      'a lantern walk along the Melaka river',
    ],
    promise: 'Designed from scratch, with real photographs. Download as PNG.',
  },
  slides: {
    opening: 'Make a slide deck about ',
    examples: [
      'the history of teh tarik',
      'why sourdough works',
      'EV adoption in Malaysia',
      'our quarterly results for the board',
    ],
    promise: 'Planned as a talk, written slide by slide. Download as PDF.',
  },
  games: {
    opening: 'Build a game: ',
    examples: [
      'snake with 3 levels, each one faster',
      'catch the falling durians before they land',
      'a typing race against the clock',
      'memory match with batik tiles',
    ],
    promise: 'Playable in the panel, tested by playing it first.',
  },
  website: {
    opening: 'Build a website for ',
    examples: [
      'my cafe in Bangsar: menu, story, how to visit',
      'a landing page for my tuition centre',
      'a portfolio for my photography',
      'our wedding in Kuching, with the day’s schedule',
    ],
    promise: 'One page or several, checked on a desktop and a phone.',
  },
  app: {
    opening: 'Build an app: ',
    examples: [
      'a spinner to pick who presents at standup',
      'a kanban board for my team',
      'a bill splitter for makan with friends',
      'a budget for my first job',
    ],
    promise: 'A tool you use, that remembers what you put in it.',
  },
}

export function showcaseOf(kind: Makeable): Showcase {
  return (
    SHOWCASE[kind.name] ?? {
      opening: `Make a ${kind.label.toLowerCase()} about `,
      examples: [kind.description],
      promise: kind.description,
    }
  )
}

/**
 * What goes into the box when a kind is picked, and which part to select.
 *
 * The subject is selected, not the whole request, so the next thing typed
 * replaces "a night market in Ipoh" and keeps "Design a poster for". Or press
 * Enter and the example is sent as it stands.
 */
export function startWith(kind: Makeable, example?: string): {
  text: string
  selection: [number, number]
} {
  const { opening } = showcaseOf(kind)
  if (!example) return { text: opening, selection: [opening.length, opening.length] }
  const text = opening + example
  return { text, selection: [opening.length, text.length] }
}

// The order a person meets them in: what is asked for most, first. The
// registry's order is whatever order the kinds were written in.
const ORDER = ['poster', 'slides', 'website', 'app', 'games']

export function inOrder(kinds: Makeable[]): Makeable[] {
  const rank = (name: string) => {
    const at = ORDER.indexOf(name)
    return at === -1 ? ORDER.length : at
  }
  return [...kinds].sort((a, b) => rank(a.name) - rank(b.name))
}

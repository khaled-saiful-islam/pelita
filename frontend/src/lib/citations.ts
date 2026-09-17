/**
 * Turning `[1]` in an answer into a link to source 1.
 *
 * The model is asked to cite inline, and it does — but as plain text, which
 * leaves the reader scrolling to a collapsed list and counting. Rewriting the
 * markers into markdown links before rendering makes them clickable with no
 * change to how the answer is produced.
 *
 * Done as a string transform rather than a rehype plugin because the rule is
 * genuinely textual, and the one hard part — not touching code — is easier to
 * reason about on the raw markdown than on a tree.
 */

export interface CitationTarget {
  rank: number
  url: string
  title: string
}

// Fenced blocks and inline spans, so their contents can be left alone. A `[1]`
// inside a code sample is array indexing, not a citation.
const CODE_SEGMENT = /(```[\s\S]*?```|`[^`\n]*`)/g

// A bare [1] or a grouped [1, 2, 3].
//
// Guarded on both sides. The lookbehind rejects `![1]` — an image — and the
// lookahead rejects `[1](…)`, which is already a link: rewriting either
// produces `[1](new)(old)`, and the second half renders as stray text.
const CITATION = /(?<!!)\[(\d+(?:\s*,\s*\d+)*)\](?!\()/g

/**
 * Rewrite citation markers as markdown links.
 *
 * Markers with no matching source are left as text — a model that cites [7]
 * when five sources exist should look wrong, not link somewhere arbitrary.
 */
export function linkCitations(markdown: string, sources: CitationTarget[]): string {
  if (sources.length === 0 || !markdown) return markdown

  const byRank = new Map(sources.map((source) => [source.rank, source]))

  // Split keeps the delimiters, so odd indices are the code segments.
  return markdown
    .split(CODE_SEGMENT)
    .map((segment, index) => (index % 2 === 1 ? segment : replaceOutsideCode(segment, byRank)))
    .join('')
}

function replaceOutsideCode(text: string, byRank: Map<number, CitationTarget>): string {
  return text.replace(CITATION, (whole, inner: string) => {
    const ranks = inner.split(',').map((part) => Number(part.trim()))
    if (ranks.some((rank) => !byRank.has(rank))) return whole

    // A group like [2, 5] becomes two adjacent links rather than one, so each
    // number goes to its own source.
    return ranks
      .map((rank) => {
        const source = byRank.get(rank)!
        return `[${rank}](${source.url} "${escapeTitle(source.title)}")`
      })
      .join('')
  })
}

function escapeTitle(title: string): string {
  return title.replace(/"/g, "'")
}

/** True when a rendered link is one of our citation markers. */
export function isCitationLabel(children: unknown): boolean {
  return typeof children === 'string' && /^\d+$/.test(children)
}

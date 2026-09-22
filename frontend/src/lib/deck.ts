/**
 * Reading a deck without running it.
 *
 * The document is model-written, so it is never executed to be understood.
 * `DOMParser` builds a tree without running scripts, loading anything or
 * touching the page, which is all that is needed to count slides and read
 * their headings.
 */

export interface SlideSummary {
  index: number
  heading: string
}

export function slidesOf(html: string): SlideSummary[] {
  try {
    const parsed = new DOMParser().parseFromString(html, 'text/html')
    return [...parsed.querySelectorAll('.slide')].map((slide, index) => ({
      index,
      heading:
        slide.querySelector('h1, h2, h3')?.textContent?.trim() ||
        slide.textContent?.trim().split('\n')[0]?.slice(0, 60) ||
        `Slide ${index + 1}`,
    }))
  } catch {
    // A document that will not parse is still a document worth showing; it
    // simply has no navigation.
    return []
  }
}

/** True when this artifact is a deck rather than a single surface. */
export function isDeck(kind: string, html: string): boolean {
  return kind === 'slides' || slidesOf(html).length > 1
}

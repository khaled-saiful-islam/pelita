import { describe, expect, it } from 'vitest'
import { isCitationLabel, linkCitations } from './citations'

const sources = [
  { rank: 1, url: 'https://one.test', title: 'First source' },
  { rank: 2, url: 'https://two.test', title: 'Second source' },
]

describe('linkCitations', () => {
  it('turns a marker into a link to the matching source', () => {
    expect(linkCitations('Rain peaks in November [1].', sources)).toBe(
      'Rain peaks in November [1](https://one.test "First source").',
    )
  })

  it('links every marker in a sentence', () => {
    const out = linkCitations('A [1] and B [2].', sources)
    expect(out).toContain('[1](https://one.test')
    expect(out).toContain('[2](https://two.test')
  })

  it('splits a grouped marker so each number gets its own link', () => {
    const out = linkCitations('Both agree [1, 2].', sources)
    expect(out).toBe(
      'Both agree [1](https://one.test "First source")[2](https://two.test "Second source").',
    )
  })

  it('leaves a marker with no matching source as plain text', () => {
    // A model citing [7] when two sources exist should look wrong, not link
    // somewhere arbitrary.
    expect(linkCitations('Claimed [7].', sources)).toBe('Claimed [7].')
  })

  it('leaves a group alone when any member is missing', () => {
    expect(linkCitations('Claimed [1, 9].', sources)).toBe('Claimed [1, 9].')
  })

  it('does not touch numbers inside a fenced code block', () => {
    const markdown = 'Use it:\n\n```python\nvalue = items[1]\n```\n\nAs shown [1].'
    const out = linkCitations(markdown, sources)
    expect(out).toContain('value = items[1]')
    expect(out).toContain('[1](https://one.test')
  })

  it('does not touch numbers inside inline code', () => {
    const out = linkCitations('Write `items[1]` to index, see [2].', sources)
    expect(out).toContain('`items[1]`')
    expect(out).toContain('[2](https://two.test')
  })

  it('does not re-wrap an existing markdown link', () => {
    const markdown = '[1](https://already.test) is already a link.'
    expect(linkCitations(markdown, sources)).toBe(markdown)
  })

  it('does not touch an image', () => {
    const markdown = '![1](https://img.test/a.png)'
    expect(linkCitations(markdown, sources)).toBe(markdown)
  })

  it('escapes quotes in a title so the link does not break', () => {
    const out = linkCitations('See [1].', [
      { rank: 1, url: 'https://x.test', title: 'The "best" guide' },
    ])
    expect(out).toBe('See [1](https://x.test "The \'best\' guide").')
  })

  it('returns the markdown untouched when there are no sources', () => {
    expect(linkCitations('Nothing to link [1].', [])).toBe('Nothing to link [1].')
  })

  it('handles empty input', () => {
    expect(linkCitations('', sources)).toBe('')
  })
})

describe('isCitationLabel', () => {
  it('recognises a bare number', () => {
    expect(isCitationLabel('3')).toBe(true)
  })

  it('rejects anything else', () => {
    expect(isCitationLabel('see here')).toBe(false)
    expect(isCitationLabel(['3'])).toBe(false)
    expect(isCitationLabel(undefined)).toBe(false)
  })
})

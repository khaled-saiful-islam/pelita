import { describe, expect, it } from 'vitest'
import { lookOf } from './kind-look'

describe('lookOf', () => {
  it('gives each kind its own colour and glyph', () => {
    const [poster, slides, games] = [lookOf('poster'), lookOf('slides'), lookOf('games')]
    const colours = new Set([poster.colour, slides.colour, games.colour])
    const glyphs = new Set([poster.icon, slides.icon, games.icon])

    expect(colours.size).toBe(3)
    expect(glyphs.size).toBe(3)
  })

  it('falls back for a kind it has never heard of', () => {
    // Kinds come from a registry on the server and this list does not, so a
    // new one must look deliberate rather than crash or come out blank.
    const unknown = lookOf('one-page-app')
    expect(unknown.icon).toBeTruthy()
    expect(unknown.colour).toBe('text-primary')
  })

  it('falls back when there is no kind yet', () => {
    expect(lookOf(undefined).colour).toBe('text-primary')
  })
})

import { describe, expect, it } from 'vitest'
import { lookOf } from './kind-look'

describe('lookOf', () => {
  it('gives each kind its own colour and glyph', () => {
    const looks = ['poster', 'slides', 'games', 'website', 'app'].map(lookOf)
    const colours = new Set(looks.map((look) => look.colour))
    const glyphs = new Set(looks.map((look) => look.icon))

    expect(colours.size).toBe(5)
    expect(glyphs.size).toBe(5)
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

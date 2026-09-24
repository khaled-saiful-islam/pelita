import { describe, expect, it } from 'vitest'
import { accentOn, contrast, readableOn } from './contrast'

describe('readableOn', () => {
  it('picks the one that can actually be read', () => {
    // The real case: a deck whose first two colours were both cream, which put
    // cream text on a cream card.
    expect(readableOn('#f4ead5', ['#e8d9b8', '#2a1a0e', '#6b4a2b'])).toBe('#2a1a0e')
  })

  it('falls back when nothing in the palette is readable', () => {
    expect(readableOn('#ffffff', ['#fefefe', '#fdfdfd'])).toBe('#111111')
    expect(readableOn('#101010', ['#111111', '#0f0f0f'])).toBe('#f5f5f5')
  })

  it('measures contrast the way every checker does', () => {
    expect(contrast('#ffffff', '#000000')).toBeCloseTo(21, 1)
    expect(contrast('#ffffff', '#ffffff')).toBeCloseTo(1, 5)
  })

  it('handles short hex and stray junk without throwing', () => {
    expect(readableOn('#fff', ['#000'])).toBe('#000')
    expect(() => readableOn('nonsense', ['#000'])).not.toThrow()
  })
})

describe('accentOn', () => {
  it('skips a pale accent on a pale ground', () => {
    // The real one: sand on paper, invisible.
    expect(accentOn('#f5efe3', '#2b2a28', ['#f5efe3', '#2b2a28', '#e8dcc6', '#b4531f'])).toBe('#b4531f')
  })

  it('falls back to the ink when nothing else can be seen', () => {
    expect(accentOn('#f5efe3', '#2b2a28', ['#f5efe3', '#2b2a28', '#ece4d4'])).toBe('#2b2a28')
  })
})

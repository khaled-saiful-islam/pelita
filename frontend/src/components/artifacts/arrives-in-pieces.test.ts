import { describe, expect, it } from 'vitest'
import { arrivesInPieces } from './arrives-in-pieces'

describe('arrivesInPieces', () => {
  it('is true for a deck, which reports each slide as it lands', () => {
    expect(arrivesInPieces({ kind: 'slides', parts: [] })).toBe(true)
  })

  it('is false for a game, which names its levels but is written in one call', () => {
    // A game showed "Writing slide 1 — Green Flag": a slide that is not a
    // slide, counted towards a total it would never reach.
    expect(arrivesInPieces({ kind: 'games', parts: [] })).toBe(false)
  })

  it('is false for a poster, which has nothing until it is finished', () => {
    expect(arrivesInPieces({ kind: 'poster', parts: [] })).toBe(false)
  })

  it('is true once pieces have actually arrived, whatever the kind', () => {
    expect(arrivesInPieces({ kind: 'anything-new', parts: [{}] })).toBe(true)
  })
})

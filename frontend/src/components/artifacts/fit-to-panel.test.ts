import { describe, expect, it } from 'vitest'
import { fitScale } from './fit-to-panel'

const PANEL = { width: 700, height: 900 }

describe('fitScale', () => {
  it('shrinks a tall poster until its height fits', () => {
    expect(fitScale({ width: 794, height: 1123 }, PANEL)).toBeCloseTo(900 / 1123)
  })

  it('shrinks a wide banner until its width fits', () => {
    expect(fitScale({ width: 2400, height: 400 }, PANEL)).toBeCloseTo(700 / 2400)
  })

  it('fits a square by whichever side is tighter', () => {
    expect(fitScale({ width: 1080, height: 1080 }, PANEL)).toBeCloseTo(700 / 1080)
  })

  it('never enlarges something already small enough', () => {
    // A poster blown up past its own size is a blurry poster.
    expect(fitScale({ width: 300, height: 300 }, PANEL)).toBe(1)
  })

  it('handles a panel narrower than it is tall, and the other way round', () => {
    const poster = { width: 1000, height: 1000 }
    expect(fitScale(poster, { width: 200, height: 900 })).toBeCloseTo(0.2)
    expect(fitScale(poster, { width: 900, height: 200 })).toBeCloseTo(0.2)
  })

  it('waits rather than guessing when there is no room measured yet', () => {
    expect(fitScale({ width: 794, height: 1123 }, { width: 0, height: 0 })).toBe(0)
  })

  it('survives an artifact that arrived with no size', () => {
    // Zero by zero renders as nothing, which looks exactly like a failure.
    expect(fitScale({ width: 0, height: 0 }, PANEL)).toBe(1)
  })
})

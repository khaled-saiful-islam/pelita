import { describe, expect, it } from 'vitest'
import { stripSource, when } from './NewsStrip'

describe('when', () => {
  const now = new Date('2026-09-24T12:00:00Z')

  it('is relative while it is recent', () => {
    expect(when('2026-09-24T09:00:00Z', now)).toBe('3h ago')
    expect(when('2026-09-21T12:00:00Z', now)).toBe('3d ago')
  })

  it('is a date once it is past a week, not "437d ago"', () => {
    const said = when('2025-07-14T07:00:00Z', now)
    expect(said).not.toMatch(/ago/)
    expect(said).toMatch(/2025/)
  })

  it('leaves the year out when it is this one', () => {
    expect(when('2026-07-07T07:00:00Z', now)).not.toMatch(/2026/)
  })
})

describe('stripSource', () => {
  it('drops the publisher Google News appends to the title', () => {
    expect(stripSource('Best kopitiams in Ipoh - Lifestyle Asia', 'Lifestyle Asia')).toBe(
      'Best kopitiams in Ipoh',
    )
  })
})

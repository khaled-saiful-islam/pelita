import { beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { usePanelWidth } from './usePanelWidth'

function widthOf(result: { current: { width: string } }): number {
  return Number(result.current.width.replace('%', ''))
}

describe('usePanelWidth', () => {
  beforeEach(() => {
    localStorage.clear()
    window.innerWidth = 1440
  })

  it('starts as the larger half, because the artifact is the thing being looked at', () => {
    const { result } = renderHook(() => usePanelWidth())
    expect(widthOf(result)).toBeGreaterThan(50)
  })

  it('remembers a width somebody chose', () => {
    localStorage.setItem('pelita.artifact-panel-width', '0.7')
    const { result } = renderHook(() => usePanelWidth())
    expect(widthOf(result)).toBeCloseTo(70, 0)
  })

  it('refuses a remembered width that would squeeze either side to nothing', () => {
    localStorage.setItem('pelita.artifact-panel-width', '0.99')
    const { result } = renderHook(() => usePanelWidth())
    expect(widthOf(result)).toBeLessThanOrEqual(80)
  })

  it('falls back to a default when storage cannot be read', () => {
    // Private windows and blocked site data both land here. A default width is
    // a fine outcome; a panel that will not render is not.
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    const { result } = renderHook(() => usePanelWidth())
    expect(widthOf(result)).toBeGreaterThan(0)
    vi.restoreAllMocks()
  })

  it('covers the conversation instead of sharing with it on a narrow window', () => {
    window.innerWidth = 700
    const { result } = renderHook(() => usePanelWidth())
    expect(result.current.narrow).toBe(true)
    expect(result.current.width).toBe('100%')
  })

  it('goes back to the default on reset', () => {
    localStorage.setItem('pelita.artifact-panel-width', '0.78')
    const { result } = renderHook(() => usePanelWidth())
    act(() => result.current.reset())
    expect(widthOf(result)).toBeCloseTo(58, 0)
  })
})

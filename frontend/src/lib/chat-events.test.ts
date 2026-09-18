import { describe, expect, it } from 'vitest'
import { mergeSources, mergeTool } from './chat-events'
import type { ToolActivity } from './chat-types'
describe('mergeSources', () => {
  const source = (rank: number) => ({
    rank,
    title: `t${rank}`,
    url: `https://e.test/${rank}`,
    snippet: '',
  })

  it('keeps the first round when a second arrives', () => {
    // Two searches in one turn: replacing left [3] pointing at nothing while
    // [8] pointed at a list of five.
    const merged = mergeSources([source(1), source(2)], [source(3), source(4)])
    expect(merged.map((s) => s.rank)).toEqual([1, 2, 3, 4])
  })

  it('sorts by rank so citation order matches the list', () => {
    expect(mergeSources([source(3)], [source(1)]).map((s) => s.rank)).toEqual([1, 3])
  })

  it('replaces a repeated rank rather than duplicating it', () => {
    const merged = mergeSources([source(1)], [{ ...source(1), title: 'newer' }])
    expect(merged).toHaveLength(1)
    expect(merged[0].title).toBe('newer')
  })

  it('starts from nothing', () => {
    expect(mergeSources(undefined, [source(1)]).map((s) => s.rank)).toEqual([1])
  })
})

describe('mergeTool across rounds', () => {
  const activity = (status: ToolActivity['status'], detail: string): ToolActivity => ({
    tool: 'web_search',
    status,
    label: 'Searching',
    detail,
  })

  it('updates a running chip in place', () => {
    const merged = mergeTool([activity('running', 'a')], activity('done', 'a'))
    expect(merged).toHaveLength(1)
    expect(merged[0].status).toBe('done')
  })

  it('gives a second run its own chip', () => {
    // Two searches are two things that happened; collapsing them hides the
    // second one's results entirely.
    const first = mergeTool(undefined, activity('running', 'a'))
    const done = mergeTool(first, activity('done', 'a'))
    const second = mergeTool(done, activity('running', 'b'))
    expect(second).toHaveLength(2)
  })
})

import { describe, expect, it } from 'vitest'
import { splitStoredSources } from './messages'
import type { ChatMessage } from '@/hooks/useChat'

function message(sources: ChatMessage['sources']): ChatMessage {
  return {
    id: 'm1',
    role: 'assistant',
    content: 'answer',
    finish_reason: 'stop',
    model: 'm',
    created_at: '2026-01-01T00:00:00Z',
    prompt_tokens: 1,
    completion_tokens: 1,
    cost: 0,
    usage_source: 'provider',
    sources,
  }
}

const citation = { rank: 1, title: 'A page', url: 'https://a.test', snippet: 'text' }
const picture = {
  rank: 1,
  title: 'A photo',
  url: 'https://page.test',
  snippet: 'Wikipedia',
  thumbnail_url: 'https://thumb.test/1.jpg',
  image_url: 'https://full.test/1.jpg',
}

describe('splitStoredSources', () => {
  it('moves image results out of sources and into images', () => {
    // Regression: images rendered while streaming and vanished on reload,
    // coming back as a list of links instead of a grid.
    const out = splitStoredSources(message([picture]))
    expect(out.images).toHaveLength(1)
    expect(out.sources).toHaveLength(0)
    expect(out.images?.[0].thumbnail_url).toBe('https://thumb.test/1.jpg')
    expect(out.images?.[0].source).toBe('Wikipedia')
  })

  it('keeps ordinary citations where they are', () => {
    const out = splitStoredSources(message([citation]))
    expect(out.sources).toHaveLength(1)
    expect(out.images).toBeUndefined()
  })

  it('separates a mixed set', () => {
    const out = splitStoredSources(message([citation, picture]))
    expect(out.sources).toHaveLength(1)
    expect(out.images).toHaveLength(1)
  })

  it('treats a result with only a full image and no thumbnail as an image', () => {
    const out = splitStoredSources(
      message([{ ...picture, thumbnail_url: null, image_url: 'https://full.test/x.jpg' }]),
    )
    expect(out.images).toHaveLength(1)
  })

  it('returns the message untouched when there are no sources', () => {
    const original = message([])
    expect(splitStoredSources(original)).toBe(original)
  })

  it('returns the message untouched when nothing is an image', () => {
    const original = message([citation, { ...citation, rank: 2 }])
    expect(splitStoredSources(original)).toBe(original)
  })
})

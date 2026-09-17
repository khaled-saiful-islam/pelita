import type { ChatMessage } from '@/hooks/useChat'

/**
 * Split a restored message's stored sources into citations and images.
 *
 * Both are persisted in one table, because an image result *is* a source — but
 * they render as very different things. Without this split a reloaded
 * conversation turns its picture grid into a list of links, which is what
 * happened: the images appeared while streaming and vanished on refresh.
 */
export function splitStoredSources(message: ChatMessage): ChatMessage {
  const stored = message.sources ?? []
  if (stored.length === 0) return message

  const images = stored.filter((source) => source.thumbnail_url || source.image_url)
  if (images.length === 0) return message

  return {
    ...message,
    sources: stored.filter((source) => !source.thumbnail_url && !source.image_url),
    images: images.map((source) => ({
      rank: source.rank,
      title: source.title,
      url: source.url,
      source: source.snippet,
      thumbnail_url: source.thumbnail_url ?? '',
      image_url: source.image_url ?? '',
    })),
  }
}

import { useCallback, useEffect, useState } from 'react'
import { apiFetch } from '@/lib/api'

export interface ConversationSummary {
  id: string
  title: string
  created_at: string
  updated_at: string
}

interface ConversationListResponse {
  items: ConversationSummary[]
  total: number
  limit: number
  offset: number
}

export function useConversations() {
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    try {
      const page = await apiFetch<ConversationListResponse>('/conversations?limit=100')
      setConversations(page.items)
    } catch {
      // The sidebar failing to load must not take the chat with it.
      setConversations([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  /**
   * Insert or move a conversation to the top without a round trip.
   *
   * Called when a stream starts, so a new chat appears in the sidebar the
   * moment it exists rather than after the answer finishes.
   */
  const upsert = useCallback((id: string, title: string) => {
    setConversations((current) => {
      const now = new Date().toISOString()
      const existing = current.find((c) => c.id === id)
      const updated: ConversationSummary = existing
        ? { ...existing, title, updated_at: now }
        : { id, title, created_at: now, updated_at: now }
      return [updated, ...current.filter((c) => c.id !== id)]
    })
  }, [])

  const rename = useCallback(async (id: string, title: string) => {
    setConversations((current) => current.map((c) => (c.id === id ? { ...c, title } : c)))
    try {
      await apiFetch<ConversationSummary>(`/conversations/${id}`, {
        method: 'PATCH',
        body: JSON.stringify({ title }),
      })
    } catch {
      void refresh() // Put the real title back.
    }
  }, [refresh])

  const remove = useCallback(async (id: string) => {
    setConversations((current) => current.filter((c) => c.id !== id))
    try {
      await apiFetch<void>(`/conversations/${id}`, { method: 'DELETE' })
    } catch {
      void refresh()
    }
  }, [refresh])

  return { conversations, loading, refresh, upsert, rename, remove }
}

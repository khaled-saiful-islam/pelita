/**
 * Chat turn state.
 *
 * Holds the message list, drives the stream, and owns stopping, regenerating
 * and rating. The transport detail — that events arrive as SSE frames — stops
 * here; components see messages and a boolean.
 */

import { useCallback, useRef, useState } from 'react'
import { apiFetch } from '@/lib/api'
import { readSse } from '@/lib/sse'

export type Role = 'user' | 'assistant'
export type Rating = 'up' | 'down'

export interface ChatMessage {
  id: string
  role: Role
  content: string
  finish_reason: string | null
  model: string | null
  created_at: string
  prompt_tokens: number
  completion_tokens: number
  cost: string | number
  /** 'provider' when the model reported the counts, 'estimated' when we did. */
  usage_source: string | null
  /** True only for the message currently being written. */
  streaming?: boolean
  error?: string | null
}

export interface Totals {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  cost: string | number
  currency: string
  /** True when any message was priced from an estimate. */
  estimated: boolean
}

interface FeedbackRecord {
  message_id: string
  rating: Rating
  reason: string | null
}

export interface ConversationDetail {
  id: string
  title: string
  created_at: string
  updated_at: string
  messages: ChatMessage[]
  feedback: Record<string, FeedbackRecord>
  language: string | null
  totals: Totals
}

interface StartPayload {
  conversation_id: string
  user_message_id: string
  assistant_message_id: string
  title: string
  language: string | null
}

interface UsagePayload {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  cost: number
  currency: string
  source: string
}

interface StreamBody {
  conversation_id?: string | null
  content?: string
  regenerate_of?: string
}

export interface UseChat {
  messages: ChatMessage[]
  conversationId: string | null
  title: string | null
  streaming: boolean
  error: string | null
  ratings: Record<string, Rating>
  language: string | null
  totals: Totals | null
  currency: string
  send: (content: string) => Promise<void>
  regenerate: (assistantMessageId: string) => Promise<void>
  rate: (messageId: string, rating: Rating | null, reason?: string) => void
  stop: () => void
  load: (conversationId: string) => Promise<void>
  reset: () => void
}

export function useChat(onConversationStarted?: (id: string, title: string) => void): UseChat {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [title, setTitle] = useState<string | null>(null)
  const [streaming, setStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [ratings, setRatings] = useState<Record<string, Rating>>({})
  const [language, setLanguage] = useState<string | null>(null)
  const [totals, setTotals] = useState<Totals | null>(null)

  const abortRef = useRef<AbortController | null>(null)
  const assistantIdRef = useRef<string | null>(null)

  const patchMessage = useCallback((id: string, patch: Partial<ChatMessage>) => {
    setMessages((current) => current.map((m) => (m.id === id ? { ...m, ...patch } : m)))
  }, [])

  const reset = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    assistantIdRef.current = null
    setMessages([])
    setConversationId(null)
    setTitle(null)
    setStreaming(false)
    setError(null)
    setRatings({})
    setLanguage(null)
    setTotals(null)
  }, [])

  const load = useCallback(async (id: string) => {
    abortRef.current?.abort()
    setError(null)
    const detail = await apiFetch<ConversationDetail>(`/conversations/${id}`)
    setConversationId(detail.id)
    setTitle(detail.title)
    setMessages(detail.messages)
    setRatings(
      Object.fromEntries(
        Object.entries(detail.feedback ?? {}).map(([id, f]) => [id, f.rating]),
      ),
    )
    setLanguage(detail.language)
    setTotals(detail.totals)
    setStreaming(false)
  }, [])

  /**
   * Stop the response.
   *
   * Two things have to happen: the server must be told, so it stops pulling
   * tokens it would otherwise be billed for and saves the partial answer; and
   * the local fetch must be aborted. Telling the server comes first — aborting
   * alone would leave the generation running.
   */
  const stop = useCallback(() => {
    const assistantId = assistantIdRef.current
    if (assistantId) {
      apiFetch<void>(`/chat/messages/${assistantId}/stop`, { method: 'POST' }).catch(() => {
        // The stream may already have finished. Not worth showing.
      })
    }
    abortRef.current?.abort()
  }, [])

  /** The stream loop, shared by sending and regenerating. */
  const run = useCallback(
    async (body: StreamBody, onStart: (start: StartPayload) => void) => {
      setError(null)
      setStreaming(true)

      const controller = new AbortController()
      abortRef.current = controller

      try {
        const response = await fetch('/api/chat/stream', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
          signal: controller.signal,
        })

        if (!response.ok || !response.body) {
          throw new Error(
            response.status === 401
              ? 'Your session expired. Sign in again.'
              : `The server refused the request (${response.status}).`,
          )
        }

        for await (const frame of readSse(response.body, controller.signal)) {
          const payload = safeParse(frame.data)
          if (!payload) continue

          switch (frame.event) {
            case 'start': {
              const start = payload as unknown as StartPayload
              assistantIdRef.current = start.assistant_message_id
              setConversationId(start.conversation_id)
              setTitle(start.title)
              setLanguage(start.language)
              onConversationStarted?.(start.conversation_id, start.title)
              onStart(start)
              break
            }
            case 'token': {
              const id = assistantIdRef.current
              if (!id) break
              const text = String(payload.text ?? '')
              setMessages((current) =>
                current.map((m) => (m.id === id ? { ...m, content: m.content + text } : m)),
              )
              break
            }
            case 'usage': {
              const u = payload as unknown as UsagePayload
              const id = assistantIdRef.current
              if (id) {
                patchMessage(id, {
                  prompt_tokens: u.prompt_tokens,
                  completion_tokens: u.completion_tokens,
                  cost: u.cost,
                  usage_source: u.source,
                })
              }
              // Roll into the running total rather than refetching: the server
              // already told us what this turn cost.
              setTotals((current) => ({
                prompt_tokens: (current?.prompt_tokens ?? 0) + u.prompt_tokens,
                completion_tokens: (current?.completion_tokens ?? 0) + u.completion_tokens,
                total_tokens: (current?.total_tokens ?? 0) + u.total_tokens,
                cost: Number(current?.cost ?? 0) + u.cost,
                currency: u.currency,
                estimated: (current?.estimated ?? false) || u.source === 'estimated',
              }))
              break
            }
            case 'error': {
              const message = String(payload.message ?? 'Something went wrong.')
              setError(message)
              if (assistantIdRef.current) {
                patchMessage(assistantIdRef.current, { error: message })
              }
              break
            }
            case 'done': {
              if (assistantIdRef.current) {
                patchMessage(assistantIdRef.current, {
                  streaming: false,
                  finish_reason: String(payload.finish_reason ?? 'stop'),
                })
              }
              break
            }
          }
        }
      } catch (err) {
        // An abort is the stop button working, not a failure.
        if (!(err instanceof DOMException && err.name === 'AbortError')) {
          setError(err instanceof Error ? err.message : 'Could not reach the server.')
        }
        if (assistantIdRef.current) {
          patchMessage(assistantIdRef.current, { streaming: false })
        }
      } finally {
        setStreaming(false)
        abortRef.current = null
        assistantIdRef.current = null
      }
    },
    [onConversationStarted, patchMessage],
  )

  const send = useCallback(
    async (content: string) => {
      const trimmed = content.trim()
      if (!trimmed || streaming) return

      // Optimistic user message, given the server's id on `start`.
      const provisionalId = `pending-${Date.now()}`
      setMessages((current) => [
        ...current,
        {
          id: provisionalId,
          role: 'user',
          content: trimmed,
          finish_reason: null,
          model: null,
          created_at: new Date().toISOString(),
          prompt_tokens: 0,
          completion_tokens: 0,
          cost: 0,
          usage_source: null,
        },
      ])

      await run({ conversation_id: conversationId, content: trimmed }, (start) => {
        setMessages((current) => [
          ...current.map((m) => (m.id === provisionalId ? { ...m, id: start.user_message_id } : m)),
          blankAssistant(start.assistant_message_id),
        ])
      })
    },
    [conversationId, streaming, run],
  )

  const regenerate = useCallback(
    async (assistantMessageId: string) => {
      if (streaming) return
      // The server reuses the same row, so the id is stable. Clearing it here
      // rather than removing and re-adding keeps scroll position steady.
      setRatings((current) => {
        const { [assistantMessageId]: _removed, ...rest } = current
        return rest
      })
      setMessages((current) =>
        current.map((m) =>
          m.id === assistantMessageId
            ? { ...m, content: '', finish_reason: null, error: null, streaming: true }
            : m,
        ),
      )
      await run({ regenerate_of: assistantMessageId }, () => {})
    },
    [streaming, run],
  )

  const rate = useCallback((messageId: string, rating: Rating | null, reason?: string) => {
    setRatings((current) => {
      if (rating === null) {
        const { [messageId]: _removed, ...rest } = current
        return rest
      }
      return { ...current, [messageId]: rating }
    })

    const request =
      rating === null
        ? apiFetch<void>(`/chat/messages/${messageId}/feedback`, { method: 'DELETE' })
        : apiFetch<FeedbackRecord>(`/chat/messages/${messageId}/feedback`, {
            method: 'PUT',
            body: JSON.stringify({ rating, reason: reason ?? null }),
          })

    request.catch(() => {
      // A rating that fails to save is not worth interrupting anyone over.
    })
  }, [])

  return {
    messages,
    conversationId,
    title,
    streaming,
    error,
    ratings,
    language,
    totals,
    currency: totals?.currency ?? 'USD',
    send,
    regenerate,
    rate,
    stop,
    load,
    reset,
  }
}

function blankAssistant(id: string): ChatMessage {
  return {
    id,
    role: 'assistant',
    content: '',
    finish_reason: null,
    model: null,
    created_at: new Date().toISOString(),
    prompt_tokens: 0,
    completion_tokens: 0,
    cost: 0,
    usage_source: null,
    streaming: true,
  }
}

function safeParse(data: string): Record<string, unknown> | null {
  try {
    return JSON.parse(data) as Record<string, unknown>
  } catch {
    return null
  }
}

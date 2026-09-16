/**
 * Chat turn state.
 *
 * Holds the message list, drives the stream, and owns stopping. The transport
 * detail — that events arrive as SSE frames — stops here; components see
 * messages and a boolean.
 */

import { useCallback, useRef, useState } from 'react'
import { apiFetch } from '@/lib/api'
import { readSse } from '@/lib/sse'

export type Role = 'user' | 'assistant'

export interface ChatMessage {
  id: string
  role: Role
  content: string
  finish_reason: string | null
  model: string | null
  created_at: string
  /** True only for the message currently being written. */
  streaming?: boolean
  error?: string | null
}

export interface ConversationDetail {
  id: string
  title: string
  created_at: string
  updated_at: string
  messages: ChatMessage[]
}

interface StartPayload {
  conversation_id: string
  user_message_id: string
  assistant_message_id: string
  title: string
}

export interface UseChat {
  messages: ChatMessage[]
  conversationId: string | null
  title: string | null
  streaming: boolean
  error: string | null
  send: (content: string) => Promise<void>
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
  }, [])

  const load = useCallback(async (id: string) => {
    abortRef.current?.abort()
    setError(null)
    const detail = await apiFetch<ConversationDetail>(`/conversations/${id}`)
    setConversationId(detail.id)
    setTitle(detail.title)
    setMessages(detail.messages)
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

  const send = useCallback(
    async (content: string) => {
      const trimmed = content.trim()
      if (!trimmed || streaming) return

      setError(null)
      setStreaming(true)

      // Optimistic user message, replaced by the server's id on `start`.
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
        },
      ])

      const controller = new AbortController()
      abortRef.current = controller

      try {
        const response = await fetch('/api/chat/stream', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ conversation_id: conversationId, content: trimmed }),
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
              onConversationStarted?.(start.conversation_id, start.title)
              setMessages((current) => [
                ...current.map((m) =>
                  m.id === provisionalId ? { ...m, id: start.user_message_id } : m,
                ),
                {
                  id: start.assistant_message_id,
                  role: 'assistant',
                  content: '',
                  finish_reason: null,
                  model: null,
                  created_at: new Date().toISOString(),
                  streaming: true,
                },
              ])
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
    [conversationId, streaming, onConversationStarted, patchMessage],
  )

  return { messages, conversationId, title, streaming, error, send, stop, load, reset }
}

function safeParse(data: string): Record<string, unknown> | null {
  try {
    return JSON.parse(data) as Record<string, unknown>
  } catch {
    return null
  }
}

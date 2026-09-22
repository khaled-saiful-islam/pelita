/**
 * Chat turn state.
 *
 * Owns the message list and the actions on it. The wire format lives in
 * `lib/chat-events.ts` and the shapes in `lib/chat-types.ts`, so what is left
 * here is what each event *means* for the conversation.
 */

import { useCallback, useRef, useState } from 'react'
import { apiFetch } from '@/lib/api'
import { readSse } from '@/lib/sse'
import {
  addUsage,
  dispatchFrame,
  mergePart,
  mergeSources,
  mergeStep,
  mergeTool,
} from '@/lib/chat-events'
import { splitStoredSources } from '@/lib/messages'
import type {
  Artifact,
  ArtifactBuild,
  AttachedFile,
  ChatMessage,
  ConversationDetail,
  FeedbackRecord,
  GuardAlert,
  Rating,
  SearchMode,
  StartPayload,
  StreamBody,
  ToolActivity,
  Totals,
} from '@/lib/chat-types'

// Re-exported so components keep importing conversation types from one place.
export type {
  Artifact,
  ArtifactBuild,
  AttachedFile,
  ChatMessage,
  ConversationDetail,
  GuardAlert,
  ImageResult,
  Rating,
  Role,
  SearchMode,
  Source,
  ToolActivity,
  Totals,
} from '@/lib/chat-types'

export interface SendOptions {
  searchMode?: SearchMode
  /** The artifact on screen, so a change refers to it rather than to nothing. */
  artifactId?: string | null
  /** Files attached but not yet sent; they become cards on this message. */
  documents?: AttachedFile[]
  /** Called with the server's id for the message, once it exists. */
  onSent?: (userMessageId: string) => void
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
  suggestions: string[]
  send: (content: string, options?: SendOptions) => Promise<void>
  regenerate: (assistantMessageId: string) => Promise<void>
  rate: (messageId: string, rating: Rating | null, reason?: string) => void
  stop: () => void
  load: (conversationId: string) => Promise<void>
  reset: () => void
  /** The artifact the panel is showing, or null for none. */
  openArtifact: string | null
  setOpenArtifact: (artifactId: string | null) => void
  /** Bumped when a turn finishes changing an artifact. */
  artifactRevision: number
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
  const [suggestions, setSuggestions] = useState<string[]>([])
  const [openArtifact, setOpenArtifact] = useState<string | null>(null)
  // Counts finished artifact builds. The panel watches it, because an edit
  // produces a new version under the same id and nothing else would tell it.
  const [artifactRevision, setArtifactRevision] = useState(0)

  const abortRef = useRef<AbortController | null>(null)
  const assistantIdRef = useRef<string | null>(null)
  // Guards and tools report before the answer exists, so they queue until there
  // is a message to attach them to.
  const pendingToolsRef = useRef<ToolActivity[]>([])
  const pendingGuardsRef = useRef<GuardAlert[]>([])

  const patch = useCallback((id: string, changes: Partial<ChatMessage>) => {
    setMessages((current) => current.map((m) => (m.id === id ? { ...m, ...changes } : m)))
  }, [])

  const patchActive = useCallback(
    (changes: Partial<ChatMessage>) => {
      const id = assistantIdRef.current
      if (id) patch(id, changes)
    },
    [patch],
  )

  /** Change the build on the answer being written. Separate from `patchActive`
   *  because every update is a function of what is already there — steps
   *  append, the document grows — and a plain patch would drop whatever
   *  arrived between the read and the write. */
  const patchBuild = useCallback(
    (change: (build: ArtifactBuild) => ArtifactBuild) => {
      const id = assistantIdRef.current
      if (!id) return
      setMessages((current) =>
        current.map((m) =>
          m.id === id && m.building ? { ...m, building: change(m.building) } : m,
        ),
      )
    },
    [],
  )

  const reset = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    assistantIdRef.current = null
    setMessages([])
    setOpenArtifact(null)
    setConversationId(null)
    setTitle(null)
    setStreaming(false)
    setError(null)
    setRatings({})
    setLanguage(null)
    setTotals(null)
    setSuggestions([])
  }, [])

  const load = useCallback(async (id: string) => {
    abortRef.current?.abort()
    setError(null)
    const detail = await apiFetch<ConversationDetail>(`/conversations/${id}`)
    setConversationId(detail.id)
    setTitle(detail.title)
    // Images and citations are stored in one table but render as very different
    // things, so a reloaded conversation has to be split back apart.
    setMessages(detail.messages.map(splitStoredSources))
    setRatings(
      Object.fromEntries(
        Object.entries(detail.feedback ?? {}).map(([key, f]) => [key, f.rating]),
      ),
    )
    setLanguage(detail.language)
    setTotals(detail.totals)
    // Chips are per-turn and not persisted.
    setSuggestions([])
    setStreaming(false)
    setOpenArtifact(null)

    // Artifacts live in their own table, so a reload has to put the cards back.
    // Wrapped because a conversation that loads without them is missing a card;
    // a conversation that fails to load is missing everything.
    try {
      const made = await apiFetch<{ items: Artifact[] }>(`/conversations/${id}/artifacts`)
      if (made.items.length) {
        setMessages((current) =>
          current.map((m) => {
            const mine = made.items.filter((a) => a.message_id === m.id)
            return mine.length ? { ...m, artifacts: mine } : m
          }),
        )
      }
    } catch {
      // No cards rather than no conversation.
    }
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

  /** Attach whatever arrived before the answer row existed. */
  const flushPending = useCallback(
    (assistantMessageId: string) => {
      const tools = pendingToolsRef.current
      const guards = pendingGuardsRef.current
      pendingToolsRef.current = []
      pendingGuardsRef.current = []
      if (tools.length > 0 || guards.length > 0) {
        patch(assistantMessageId, {
          ...(tools.length > 0 && { tools }),
          ...(guards.length > 0 && { guards }),
        })
      }
    },
    [patch],
  )

  /** The stream loop, shared by sending and regenerating. */
  const run = useCallback(
    async (body: StreamBody, onStart: (start: StartPayload) => void) => {
      setError(null)
      setStreaming(true)
      setSuggestions([])
      pendingToolsRef.current = []
      pendingGuardsRef.current = []

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
          throw new Error(await refusalMessage(response))
        }

        for await (const frame of readSse(response.body, controller.signal)) {
          dispatchFrame(frame, {
            onStart: (start) => {
              assistantIdRef.current = start.assistant_message_id
              setConversationId(start.conversation_id)
              setTitle(start.title)
              setLanguage(start.language)
              onConversationStarted?.(start.conversation_id, start.title)
              onStart(start)
              flushPending(start.assistant_message_id)
            },
            onGuard: (alert) => {
              const id = assistantIdRef.current
              if (!id) {
                pendingGuardsRef.current = [...pendingGuardsRef.current, alert]
                return
              }
              setMessages((current) =>
                current.map((m) =>
                  m.id === id ? { ...m, guards: [...(m.guards ?? []), alert] } : m,
                ),
              )
            },
            onTool: (activity) => {
              const id = assistantIdRef.current
              if (!id) {
                pendingToolsRef.current = mergeTool(pendingToolsRef.current, activity)
                return
              }
              setMessages((current) =>
                current.map((m) =>
                  m.id === id ? { ...m, tools: mergeTool(m.tools, activity) } : m,
                ),
              )
            },
            onImages: (images) => patchActive({ images }),
            onSources: (sources) => {
              const id = assistantIdRef.current
              if (!id) return
              setMessages((current) =>
                current.map((m) =>
                  m.id === id ? { ...m, sources: mergeSources(m.sources, sources) } : m,
                ),
              )
            },
            onToken: (text) => {
              const id = assistantIdRef.current
              if (!id) return
              setMessages((current) =>
                current.map((m) => (m.id === id ? { ...m, content: m.content + text } : m)),
              )
            },
            onUsage: (usage) => {
              patchActive({
                prompt_tokens: usage.prompt_tokens,
                completion_tokens: usage.completion_tokens,
                cost: usage.cost,
                usage_source: usage.source,
              })
              // Rolled in rather than refetched: the server already said what
              // this turn cost.
              setTotals((current) => addUsage(current, usage))
            },
            onArtifactStart: (start) => {
              setOpenArtifact(null)
              patchActive({
                building: { ...start, steps: [], source: '', parts: [], failed: null },
              })
            },
            onArtifactStep: (step) => {
              patchBuild((build) => ({ ...build, steps: mergeStep(build.steps, step) }))
            },
            onArtifactDelta: (text) => {
              patchBuild((build) => ({ ...build, source: build.source + text }))
            },
            onArtifactPlan: (titles) => {
              patchBuild((build) => ({ ...build, plan: titles }))
            },
            onArtifactDesign: (design) => {
              patchBuild((build) => ({ ...build, design }))
            },
            onArtifactPart: (part) => {
              patchBuild((build) => ({ ...build, parts: mergePart(build.parts, part) }))
            },
            onArtifactDone: (artifact) => {
              const id = assistantIdRef.current
              if (id) {
                setMessages((current) =>
                  current.map((m) =>
                    m.id === id
                      ? { ...m, building: null, artifacts: [...(m.artifacts ?? []), artifact] }
                      : m,
                  ),
                )
              }
              // Opened as soon as it exists, and bumped either way: an edit
              // keeps the same id, so this is what tells the panel to look
              // again.
              setOpenArtifact(artifact.id)
              setArtifactRevision((n) => n + 1)
            },
            onArtifactFailed: (failure) => {
              patchBuild((build) => ({ ...build, failed: failure.message }))
            },
            onSuggestions: setSuggestions,
            onError: (message) => {
              setError(message)
              patchActive({ error: message })
            },
            onDone: (finishReason) =>
              patchActive({ streaming: false, finish_reason: finishReason }),
          })
        }
      } catch (err) {
        // An abort is the stop button working, not a failure.
        if (!(err instanceof DOMException && err.name === 'AbortError')) {
          setError(err instanceof Error ? err.message : 'Could not reach the server.')
        }
        patchActive({ streaming: false })
      } finally {
        setStreaming(false)
        abortRef.current = null
        assistantIdRef.current = null
      }
    },
    [onConversationStarted, patch, patchActive, flushPending],
  )

  const send = useCallback(
    async (content: string, options?: SendOptions) => {
      const trimmed = content.trim()
      if (!trimmed || streaming) return

      // Optimistic user message, given the server's id on `start`.
      const provisionalId = `pending-${Date.now()}`
      const documents = options?.documents ?? []
      setMessages((current) => [
        ...current,
        { ...newMessage(provisionalId, 'user', trimmed), documents },
      ])

      await run(
        {
          conversation_id: conversationId,
          content: trimmed,
          search_mode: options?.searchMode ?? 'auto',
          artifact_id: options?.artifactId ?? null,
        },
        (start) => {
          // The optimistic message takes the server's real id, so anything that
          // later addresses it — a rating, an export, a reload — matches. The
          // files move with it: the server bound them to this same id in the
          // transaction that saved the question.
          setMessages((current) => [
            ...current.map((m) =>
              m.id === provisionalId
                ? {
                    ...m,
                    id: start.user_message_id,
                    documents: documents.map((d) => ({
                      ...d,
                      message_id: start.user_message_id,
                    })),
                  }
                : m,
            ),
            { ...newMessage(start.assistant_message_id, 'assistant', ''), streaming: true },
          ])
          options?.onSent?.(start.user_message_id)
        },
      )
    },
    [conversationId, streaming, run],
  )

  const regenerate = useCallback(
    async (assistantMessageId: string) => {
      if (streaming) return
      // The server reuses the same row, so the id is stable. Clearing in place
      // rather than removing and re-adding keeps scroll position steady.
      setRatings((current) => {
        const { [assistantMessageId]: _removed, ...rest } = current
        return rest
      })
      patch(assistantMessageId, {
        content: '',
        finish_reason: null,
        error: null,
        streaming: true,
        sources: undefined,
        images: undefined,
      })
      await run({ regenerate_of: assistantMessageId }, () => {})
    },
    [streaming, run, patch],
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
    suggestions,
    send,
    regenerate,
    rate,
    stop,
    load,
    reset,
    openArtifact,
    setOpenArtifact,
    artifactRevision,
  }
}

/**
 * Why the server would not start the turn.
 *
 * The body carries the actual reason — which allowance ran out, how much was
 * used — and "the server refused the request (429)" throws all of that away at
 * exactly the moment someone needs it.
 */
async function refusalMessage(response: Response): Promise<string> {
  if (response.status === 401) return 'Your session expired. Sign in again.'
  try {
    const body = (await response.json()) as { error?: { message?: string } }
    if (body?.error?.message) return body.error.message
  } catch {
    // Not our envelope — a proxy error page, say.
  }
  return `The server refused the request (${response.status}).`
}

function newMessage(id: string, role: 'user' | 'assistant', content: string): ChatMessage {
  return {
    id,
    role,
    content,
    finish_reason: null,
    model: null,
    created_at: new Date().toISOString(),
    prompt_tokens: 0,
    completion_tokens: 0,
    cost: 0,
    usage_source: null,
  }
}

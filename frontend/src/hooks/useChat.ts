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
  // Which conversation is on screen, and which one the running stream belongs
  // to. A build takes minutes; leaving to read something else used to abort it,
  // and because an artifact is only stored once it is finished, coming back
  // found nothing — no panel, no card, and the work thrown away. The stream now
  // outlives the switch, and its writes are scoped so they cannot land in
  // whichever conversation happens to be on screen.
  const onScreenRef = useRef<string | null>(null)
  const streamingForRef = useRef<string | null>(null)

  /** Whether the running stream is still writing to what the person is
   *  looking at. A background build keeps going; it just stops touching the
   *  screen. */
  const showing = useCallback(
    () => streamingForRef.current === null || streamingForRef.current === onScreenRef.current,
    [],
  )

  // The answer being streamed, kept per conversation.
  //
  // `load()` replaces the transcript with what the server has, and the server
  // has nothing until the turn ends — a half-written answer and its build are
  // client state and nowhere else. Leaving mid-build therefore erased them,
  // and suppressing the stream's writes while away meant everything that
  // arrived in the meantime was lost too: coming back found the question and
  // no answer.
  //
  // So the in-flight answer is buffered here regardless of what is on screen,
  // and put back when the person returns to it.
  const parked = useRef<Map<string, ChatMessage>>(new Map())

  /** Change the answer being streamed. The only way the stream touches it. */
  const answer = useCallback(
    (change: (message: ChatMessage) => ChatMessage) => {
      const id = assistantIdRef.current
      if (!id) return
      const forConversation = streamingForRef.current
      if (forConversation) {
        const held = parked.current.get(forConversation)
        if (held?.id === id) parked.current.set(forConversation, change(held))
      }
      if (!showing()) return
      setMessages((current) =>
        current.map((m) => {
          if (m.id !== id) return m
          const next = change(m)
          if (forConversation) parked.current.set(forConversation, next)
          return next
        }),
      )
    },
    [showing],
  )
  // Guards and tools report before the answer exists, so they queue until there
  // is a message to attach them to.
  const pendingToolsRef = useRef<ToolActivity[]>([])
  const pendingGuardsRef = useRef<GuardAlert[]>([])

  const patch = useCallback(
    (id: string, changes: Partial<ChatMessage>) => {
      if (!showing()) return
      setMessages((current) => current.map((m) => (m.id === id ? { ...m, ...changes } : m)))
    },
    [showing],
  )

  const patchActive = useCallback(
    (changes: Partial<ChatMessage>) => answer((m) => ({ ...m, ...changes })),
    [answer],
  )

  /** Change the build on the answer being written. Separate from `patchActive`
   *  because every update is a function of what is already there — steps
   *  append, the document grows — and a plain patch would drop whatever
   *  arrived between the read and the write. */
  const patchBuild = useCallback(
    (change: (build: ArtifactBuild) => ArtifactBuild) => {
      answer((m) => (m.building ? { ...m, building: change(m.building) } : m))
    },
    [answer],
  )

  const reset = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    assistantIdRef.current = null
    streamingForRef.current = null
    onScreenRef.current = null
    parked.current.clear()
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
    // Deliberately does not abort. A build in another conversation keeps
    // running so it finishes and is stored; coming back finds it there.
    setError(null)
    onScreenRef.current = id
    const detail = await apiFetch<ConversationDetail>(`/conversations/${id}`)
    setConversationId(detail.id)
    setTitle(detail.title)
    // Images and citations are stored in one table but render as very different
    // things, so a reloaded conversation has to be split back apart.
    const stored = detail.messages.map(splitStoredSources)
    const live = parked.current.get(id)
    setMessages(
      live ? [...stored.filter((m) => m.id !== live.id), live] : stored,
    )
    setRatings(
      Object.fromEntries(
        Object.entries(detail.feedback ?? {}).map(([key, f]) => [key, f.rating]),
      ),
    )
    setLanguage(detail.language)
    setTotals(detail.totals)
    // Chips are per-turn and not persisted.
    setSuggestions([])
    setStreaming(streamingForRef.current === id)
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

  /**
   * Whether the turn finished anyway, after the connection to it was lost.
   *
   * Given a little time — the server may still have been writing when the
   * connection went — the conversation is fetched again. An answer with
   * something in it means the work survived, and it is shown as though
   * nothing happened.
   */
  const finished = useCallback(
    async (conversation: string | null): Promise<boolean> => {
      const id = assistantIdRef.current
      if (!conversation || !id) return false
      for (const wait of [1200, 3000, 6000]) {
        await new Promise((go) => setTimeout(go, wait))
        try {
          const detail = await apiFetch<ConversationDetail>(`/conversations/${conversation}`)
          const answered = detail.messages.find((m) => m.id === id)
          if (!answered?.content && !(answered?.artifacts ?? []).length) continue
          parked.current.delete(conversation)
          if (onScreenRef.current === conversation) {
            setMessages(detail.messages.map(splitStoredSources))
            setTotals(detail.totals)
          }
          return true
        } catch {
          // Still unreachable. Try again, then give up and say so.
        }
      }
      return false
    },
    [],
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
      streamingForRef.current = onScreenRef.current

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
              // A new chat has no id until now, so both refs learn it here —
              // otherwise the first turn of a brand-new conversation would be
              // treated as belonging to nothing and stop drawing.
              if (streamingForRef.current === null) {
                streamingForRef.current = start.conversation_id
                onScreenRef.current = start.conversation_id
              }
              // Registered before anything is written to it, so leaving at any
              // point after this finds something to come back to.
              parked.current.set(start.conversation_id, {
                ...newMessage(start.assistant_message_id, 'assistant', ''),
                streaming: true,
              })
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
              answer((m) => ({ ...m, guards: [...(m.guards ?? []), alert] }))
            },
            onTool: (activity) => {
              const id = assistantIdRef.current
              if (!id) {
                pendingToolsRef.current = mergeTool(pendingToolsRef.current, activity)
                return
              }
              answer((m) => ({ ...m, tools: mergeTool(m.tools, activity) }))
            },
            onImages: (images) => patchActive({ images }),
            onSources: (sources) => {
              answer((m) => ({ ...m, sources: mergeSources(m.sources, sources) }))
            },
            onToken: (text) => {
              answer((m) => ({ ...m, content: m.content + text }))
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
              if (showing()) setTotals((current) => addUsage(current, usage))
            },
            onArtifactStart: (start) => {
              if (showing()) setOpenArtifact(null)
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
              // The shape is kept beside the look rather than inside it: the
              // panel asks for the artifact's proportions, not its palette.
              patchBuild((build) => ({
                ...build,
                design,
                width: design.width || build.width,
                height: design.height || build.height,
              }))
            },
            onArtifactPart: (part) => {
              patchBuild((build) => ({ ...build, parts: mergePart(build.parts, part) }))
            },
            onArtifactDone: (artifact) => {
              answer((m) => ({
                ...m,
                building: null,
                artifacts: [...(m.artifacts ?? []), artifact],
              }))
              // Opened as soon as it exists, and bumped either way: an edit
              // keeps the same id, so this is what tells the panel to look
              // again.
              // Only opened for somebody who is here to see it. A build that
              // finished while they were reading something else is waiting in
              // its own conversation, not thrown at the one they are in.
              if (showing()) {
                setOpenArtifact(artifact.id)
                setArtifactRevision((n) => n + 1)
              }
            },
            onArtifactFailed: (failure) => {
              patchBuild((build) => ({ ...build, failed: failure.message }))
            },
            onSuggestions: (chips: string[]) => {
              if (showing()) setSuggestions(chips)
            },
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
          // The connection going away does not mean the turn did. A build runs
          // for minutes, and a browser will suspend a connection that old on a
          // backgrounded tab — `ERR_NETWORK_IO_SUSPENDED` — while the server
          // carries on and stores the result. Reported as an error, that is a
          // scary message in front of work that actually succeeded, which a
          // refresh then reveals. So ask the server before saying anything.
          const recovered = await finished(streamingForRef.current)
          if (!recovered) {
            setError(err instanceof Error ? err.message : 'Could not reach the server.')
          }
        }
        patchActive({ streaming: false })
      } finally {
        if (showing()) setStreaming(false)
        if (streamingForRef.current) parked.current.delete(streamingForRef.current)
        streamingForRef.current = null
        abortRef.current = null
        assistantIdRef.current = null
      }
    },
    [onConversationStarted, patch, patchActive, flushPending, showing, answer, finished],
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

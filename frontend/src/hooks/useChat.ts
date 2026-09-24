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
import {
  REJOINS,
  openTurn,
  pauseBefore,
  refusalMessage,
  wasAborted,
  type Opening,
} from '@/lib/turn'
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
    async (conversation: string | null, id: string | null): Promise<boolean> => {
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

  /**
   * Follow a turn to its end — the one being started, or one already running.
   *
   * The loop is the point. A turn lives on the server now rather than inside
   * the request that asked for it, so a connection going away is not the end
   * of the work: a socket suspended on a backgrounded tab, a flaky network, a
   * build that outlasts a proxy's idle timeout. Each attempt after the first
   * asks to *follow* what is already running instead of starting anything,
   * and the server replays it from its first event — so what comes back on
   * screen is the whole build, not whatever happens to be left of it.
   */
  const run = useCallback(
    async (opening: Opening, onStart: (start: StartPayload) => void) => {
      setError(null)
      setSuggestions([])
      pendingToolsRef.current = []
      pendingGuardsRef.current = []

      const controller = new AbortController()
      abortRef.current = controller
      // Claimed before the first await, so a second visit to this conversation
      // cannot open a second reader of the same turn while this one is still
      // connecting — which would deliver every token twice.
      streamingForRef.current =
        opening.kind === 'follow' ? opening.conversation : onScreenRef.current
      // A follow waits for the server to confirm there is something to follow;
      // a start disables the composer straight away.
      if (opening.kind === 'start') setStreaming(true)

      let next = opening
      let rejoins = 0
      let lost: string | null = null

      while (true) {
        let refused = false
        try {
          const response = await openTurn(next, controller.signal)
          // Nothing to follow: the ordinary answer for a conversation with no
          // turn running in it, and not worth reporting to anyone.
          if (response === null) break

          if (!response.ok || !response.body) {
            refused = true
            throw new Error(await refusalMessage(response))
          }
          lost = null
          setStreaming(showing())

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
                // A blank answer, every time this event arrives. Following a
                // turn replays it from the beginning, so starting from whatever
                // is already there would write the answer out twice.
                const blank: ChatMessage = {
                  ...newMessage(start.assistant_message_id, 'assistant', ''),
                  streaming: true,
                }
                // Registered before anything is written to it, so leaving at any
                // point after this finds something to come back to.
                parked.current.set(start.conversation_id, blank)
                if (showing()) {
                  setMessages((current) =>
                    current.some((m) => m.id === blank.id)
                      ? current.map((m) => (m.id === blank.id ? blank : m))
                      : [...current, blank],
                  )
                }
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
          break
        } catch (err) {
          // An abort is the stop button working, or this tab going away. Not a
          // failure, and nothing to recover.
          if (wasAborted(err)) break
          lost = err instanceof Error ? err.message : 'Could not reach the server.'
          const conversation = streamingForRef.current
          // A refusal is an answer, not a dropped connection: the allowance ran
          // out, or the session expired. Asking again would only be refused.
          if (refused || !conversation || rejoins >= REJOINS) break
          await new Promise((go) => setTimeout(go, pauseBefore(rejoins)))
          rejoins += 1
          next = { kind: 'follow', conversation }
        }
      }

      const conversation = streamingForRef.current
      const assistant = assistantIdRef.current
      patchActive({ streaming: false })
      if (showing()) setStreaming(false)
      streamingForRef.current = null
      abortRef.current = null
      assistantIdRef.current = null

      if (lost !== null) {
        // Out of rejoins. The turn may still have finished while we were
        // failing to reach it — a build runs for minutes, and the server
        // stores what it made whether or not anyone is connected. Reported as
        // an error, that is a frightening message in front of work that
        // actually succeeded, which a refresh then reveals. So ask first.
        const recovered = await finished(conversation, assistant)
        if (!recovered) setError(lost)
      }
      if (conversation) parked.current.delete(conversation)
    },
    [onConversationStarted, patch, patchActive, flushPending, showing, answer, finished],
  )

  // `run` is rebuilt whenever anything it closes over changes, which is most
  // renders. `load` is a dependency of an effect in the page that resets the
  // chat when it fires with no conversation — so a `load` that changed with
  // `run` made that effect re-run, and the reset aborted the stream this hook
  // had just started. Reaching `run` through a ref keeps `load` stable, and
  // the effect fires when the route changes and at no other time.
  const latestRun = useRef(run)
  latestRun.current = run

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

    // Whatever this conversation is in the middle of. The server holds the
    // turn, not the connection that asked for it, so a build that was running
    // when the page was closed — or when the connection dropped, or when the
    // person walked away for ten minutes — is still running and can be picked
    // up from its first event. Unless this tab is already the one reading it,
    // in which case following it again would draw everything twice.
    if (streamingForRef.current === null) {
      void latestRun.current({ kind: 'follow', conversation: id }, () => {})
    }

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
          kind: 'start',
          body: {
            conversation_id: conversationId,
            content: trimmed,
            search_mode: options?.searchMode ?? 'auto',
            artifact_id: options?.artifactId ?? null,
          },
        },
        (start) => {
          // The optimistic message takes the server's real id, so anything that
          // later addresses it — a rating, an export, a reload — matches. The
          // files move with it: the server bound them to this same id in the
          // transaction that saved the question. The answer's own row is put up
          // by the shared handler, which has to do it for a turn picked up
          // later too.
          setMessages((current) =>
            current.map((m) =>
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
          )
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
      await run({ kind: 'start', body: { regenerate_of: assistantMessageId } }, () => {})
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

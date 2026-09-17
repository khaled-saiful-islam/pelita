"""The chat turn.

Four phases, in order:

    open      persist the question, reserve a row for the answer
    prepare   guards, tool selection, tool execution
    generate  assemble the prompt and stream the model
    close     persist what arrived, then suggestions and memory

Each phase is a small method that yields events and records into `TurnState`.
That shape is deliberate. Today a pattern picks the tool; when a model picks it
instead, only `_select_tool` changes. An agent loop becomes "run prepare and
generate until the model stops asking for tools" rather than a rewrite.

Transactions are short and explicit. A streaming response can stay open for
minutes, and holding a database transaction that long would pin a connection and
block migrations for as long as someone is reading an answer.
"""

from __future__ import annotations

import logging
from asyncio import Event
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from time import perf_counter
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.context.base import (
    AttachedDocument,
    ContextContributor,
    StoredMessage,
    TurnContext,
)
from app.context.pipeline import build_messages
from app.core.errors import NotFoundError, ValidationError
from app.core.tokens import count_message_tokens, count_tokens
from app.db.models.conversation import Conversation, Message
from app.db.models.source import MessageSource
from app.db.repositories.conversations import SqlConversationRepository
from app.guards.base import ContentSource, Guard, GuardVerdict
from app.providers.base import (
    ChatMessage,
    ChatRequest,
    FinishReason,
    LLMProvider,
    ProviderError,
    Role,
    TokenBudget,
    TokenEvent,
    ToolResult,
    Usage,
    UsageSource,
)
from app.providers.base import UsageEvent as ProviderUsageEvent
from app.services.accounting_service import Accounting, Pricing, price
from app.services.cancellation import CancellationRegistry
from app.services.document_service import DocumentService
from app.services.events import (
    AccountingEvent,
    ChatEvent,
    DeltaEvent,
    DoneEvent,
    ErrorEvent,
    ImagesEvent,
    SourcesEvent,
    StartEvent,
    SuggestionsEvent,
    ToolEvent,
    guard_payload,
)
from app.services.language_service import detect_language
from app.services.memory_service import MemoryService
from app.services.search_intent import SearchDecision, decide
from app.services.suggestion_service import suggest
from app.tools.base import Tool, ToolUnavailable

logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 32_000
HISTORY_MESSAGE_LIMIT = 50
TITLE_MAX_LENGTH = 60

SessionMaker = Callable[[], AbstractAsyncContextManager[AsyncSession]]
# Built per turn rather than once, because the memory contributor needs this
# user's facts and those change between requests.
ContributorFactory = Callable[[tuple[str, ...]], tuple[ContextContributor, ...]]


@dataclass(frozen=True, slots=True)
class TurnSettings:
    """Everything a turn reads from configuration.

    Grouped so the service takes a handful of collaborators rather than a
    parameter list nobody can hold in their head.
    """

    budget: TokenBudget
    pricing: Pricing
    max_tokens: int = 2048
    temperature: float = 0.7
    supported_languages: tuple[str, ...] = ("en",)
    default_language: str = "en"
    suggestions_enabled: bool = True
    suggestions_count: int = 3
    memory_auto_extract: bool = True
    memory_max_per_user: int = 100
    document_max_bytes: int = 5 * 1024 * 1024
    document_max_per_conversation: int = 3


@dataclass(slots=True)
class TurnState:
    """What the turn accumulates as it runs.

    The one mutable thing in the flow, on purpose: everything crossing a
    boundary is frozen, and this is the accumulator the phases write into.
    """

    question: str
    history: tuple[StoredMessage, ...] = ()
    language: str | None = None
    tool_results: tuple[ToolResult, ...] = ()
    image_results: tuple[ToolResult, ...] = ()
    prompt: tuple[ChatMessage, ...] = ()
    chunks: list[str] = field(default_factory=list)
    usage: Usage | None = None
    finish: FinishReason = FinishReason.STOP
    error: str | None = None

    @property
    def answer(self) -> str:
        return "".join(self.chunks)

    @property
    def citations(self) -> tuple[ToolResult, ...]:
        return (*self.tool_results, *self.image_results)


def derive_title(text: str) -> str:
    """A title from the first message, so a conversation is never called
    'New chat' in the sidebar while you are reading it."""
    cleaned = " ".join(text.split())
    if len(cleaned) <= TITLE_MAX_LENGTH:
        return cleaned or "New chat"
    cut = cleaned[:TITLE_MAX_LENGTH]
    # Prefer a word boundary, but not one that leaves almost nothing.
    space = cut.rfind(" ")
    if space > TITLE_MAX_LENGTH // 2:
        cut = cut[:space]
    return cut.rstrip(",.;:!?-") + "…"


class ChatService:
    def __init__(
        self,
        *,
        session_maker: SessionMaker,
        provider: LLMProvider,
        contributor_factory: ContributorFactory,
        cancellation: CancellationRegistry,
        settings: TurnSettings,
        tools: dict[str, Tool] | None = None,
        guards: tuple[Guard, ...] = (),
    ) -> None:
        self._session_maker = session_maker
        self._provider = provider
        self._build_contributors = contributor_factory
        self._cancellation = cancellation
        self._settings = settings
        self._tools = tools or {}
        self._guards = guards

    # -- public ----------------------------------------------------------

    async def stream_turn(
        self,
        *,
        user_id: UUID,
        conversation_id: UUID | None,
        content: str = "",
        regenerate_of: UUID | None = None,
        search_mode: str = "auto",
    ) -> AsyncIterator[ChatEvent]:
        start, state = await self._open(user_id, conversation_id, content, regenerate_of)
        yield start

        assistant_id = start.assistant_message_id
        cancel = self._cancellation.register(assistant_id)

        try:
            # Loaded before the tool decision, because attached files change
            # what an ambiguous question is probably about.
            documents = await self._documents_for(start.conversation_id)
            async for event in self._prepare(
                state, search_mode, has_documents=bool(documents)
            ):
                yield event
            async for event in self._generate(state, start, user_id, cancel, documents):
                yield event
        except ProviderError as exc:
            state.finish, state.error = FinishReason.ERROR, exc.message
            logger.warning("provider failed during turn %s: %s", assistant_id, exc.message)
        except Exception:
            state.finish = FinishReason.ERROR
            state.error = "Something went wrong generating the response."
            logger.exception("unexpected failure during turn %s", assistant_id)
        finally:
            self._cancellation.release(assistant_id)
            accounting = await self._close(assistant_id, state)

        yield AccountingEvent(accounting=accounting)
        async for event in self._follow_up(state, user_id):
            yield event
        if state.error is not None:
            yield ErrorEvent(message=state.error)
        yield DoneEvent(finish_reason=state.finish)

    async def stop(self, *, user_id: UUID, message_id: UUID) -> bool:
        """Cancel an in-flight response. Ownership is checked first."""
        async with self._session_maker() as session:
            repo = SqlConversationRepository(session)
            message = await repo.get_message(message_id)
            if message is None:
                raise NotFoundError("No such message.")
            if await repo.get(message.conversation_id, user_id) is None:
                raise NotFoundError("No such message.")
        return self._cancellation.cancel(message_id)

    # -- phase 1: open ---------------------------------------------------

    async def _open(
        self,
        user_id: UUID,
        conversation_id: UUID | None,
        content: str,
        regenerate_of: UUID | None,
    ) -> tuple[StartEvent, TurnState]:
        if regenerate_of is not None:
            return await self._begin_regeneration(user_id, regenerate_of)

        content = content.strip()
        if not content:
            raise ValidationError("Message cannot be empty.")
        if len(content) > MAX_MESSAGE_LENGTH:
            raise ValidationError(
                f"Message is too long ({len(content)} characters, "
                f"limit {MAX_MESSAGE_LENGTH})."
            )
        return await self._begin_turn(user_id, conversation_id, content)

    # -- phase 2: prepare ------------------------------------------------

    async def _prepare(
        self, state: TurnState, search_mode: str, *, has_documents: bool
    ) -> AsyncIterator[ChatEvent]:
        """Guards, then whichever tool the turn calls for."""
        for verdict in self._scan(state.question, ContentSource.USER_INPUT):
            yield guard_payload(verdict)

        decision = await self._should_search(
            search_mode, state.question, has_documents=has_documents
        )
        tool = self._select_tool(decision)
        if tool is None:
            return

        async for event in self._run_tool(tool, state, decision):
            yield event

    def _select_tool(self, decision: SearchDecision) -> Tool | None:
        """The only place a tool is chosen.

        Replace this with a model doing the choosing and everything around it
        still works, which is the whole reason tools have a protocol.
        """
        if not decision.needs_search:
            return None
        return self._tools.get("image_search" if decision.wants_images else "web_search")

    async def _run_tool(
        self, tool: Tool, state: TurnState, decision: SearchDecision
    ) -> AsyncIterator[ChatEvent]:
        yield ToolEvent(
            tool=tool.name,
            status="running",
            label=tool.presentation.running,
            detail=decision.reason,
        )

        started = perf_counter()
        try:
            found = tuple(await tool.run(query=state.question))
        except ToolUnavailable as exc:
            # A failed tool degrades the answer; it does not end the turn. The
            # model answers from what it knows and the UI says what was missed.
            logger.info("tool %s unavailable: %s", tool.name, exc)
            yield ToolEvent(
                tool=tool.name, status="failed", label="Search unavailable", detail=str(exc)
            )
            return

        yield ToolEvent(
            tool=tool.name,
            status="done",
            label=tool.presentation.done,
            detail=_summarise(len(found), tool.presentation.noun, started),
        )

        if any(result.is_image for result in found):
            state.image_results = found
            yield ImagesEvent(images=found)
            return

        # Retrieved pages are the realistic injection vector: nobody asked that
        # page for instructions. Scanned before any contributor sees them.
        state.tool_results, verdicts = self._scan_results(found)
        for verdict in verdicts:
            yield guard_payload(verdict)
        if state.tool_results:
            yield SourcesEvent(sources=state.tool_results)

    # -- phase 3: generate -----------------------------------------------

    async def _generate(
        self,
        state: TurnState,
        start: StartEvent,
        user_id: UUID,
        cancel: Event,
        documents: tuple[AttachedDocument, ...],
    ) -> AsyncIterator[ChatEvent]:
        memories = await self._memories_for(user_id)
        turn = TurnContext(
            conversation_id=start.conversation_id,
            user_id=user_id,
            user_message=state.question,
            model=self._provider.info.model,
            history=state.history,
            budget=self._settings.budget,
            language=state.language,
            tool_results=state.citations,
            documents=documents,
        )
        state.prompt, trace = await build_messages(turn, self._build_contributors(memories))
        logger.info("prompt assembled for %s: %s", start.assistant_message_id, trace.as_dict())

        request = ChatRequest(
            messages=state.prompt,
            model=self._provider.info.model,
            temperature=self._settings.temperature,
            max_tokens=self._settings.max_tokens,
            stream=True,
        )

        async for event in self._provider.stream_chat(request):
            if cancel.is_set():
                state.finish = FinishReason.STOPPED
                break
            if isinstance(event, TokenEvent):
                state.chunks.append(event.text)
                yield DeltaEvent(text=event.text)
            elif isinstance(event, ProviderUsageEvent):
                state.usage = event.usage

    # -- phase 4: close --------------------------------------------------

    async def _close(self, assistant_id: UUID, state: TurnState) -> Accounting:
        """Persist whatever arrived, however the turn ended.

        A cancelled or failed turn still consumed tokens, so it is still priced,
        and a partial answer the user watched appear should still be there on
        reload.
        """
        accounting = price(state.usage or self._estimate(state), self._settings.pricing)

        async with self._session_maker() as session:
            message = await SqlConversationRepository(session).get_message(assistant_id)
            if message is None:  # pragma: no cover - only if deleted mid-stream
                logger.warning("assistant message %s vanished before persist", assistant_id)
                return accounting

            message.content = state.answer
            message.finish_reason = state.finish
            message.prompt_tokens = accounting.prompt_tokens
            message.completion_tokens = accounting.completion_tokens
            message.cost = accounting.cost
            message.usage_source = str(accounting.source)

            if state.citations:
                # Replaced wholesale, so regenerating does not accumulate
                # citations from the previous attempt.
                message.sources = [
                    MessageSource(
                        message_id=message.id,
                        tool=source.tool,
                        title=source.title[:500],
                        url=source.url,
                        snippet=source.snippet,
                        rank=source.rank,
                        thumbnail_url=source.thumbnail_url or None,
                        image_url=source.image_url or None,
                    )
                    for source in state.citations
                ]

        return accounting

    async def _follow_up(self, state: TurnState, user_id: UUID) -> AsyncIterator[ChatEvent]:
        """Suggestions and memory extraction, only after a clean finish.

        Following up on a half-written answer wastes a call and reads as the app
        not noticing it was stopped; learning from one means learning from
        something the user did not accept.
        """
        if state.finish is not FinishReason.STOP or not state.answer.strip():
            return

        if self._settings.suggestions_enabled:
            items = await suggest(
                self._provider,
                user_message=state.question,
                assistant_message=state.answer,
                count=self._settings.suggestions_count,
            )
            if items:
                yield SuggestionsEvent(items=tuple(items))

        if self._settings.memory_auto_extract:
            await self._extract_memories(user_id, state.question, state.answer)

    # -- guards ----------------------------------------------------------

    def _scan(self, text: str, source: ContentSource) -> list[GuardVerdict]:
        """Run every guard over one piece of text, returning only what fired."""
        flagged: list[GuardVerdict] = []
        for guard in self._guards:
            try:
                verdict = guard.inspect(text, source)
            except Exception:  # noqa: BLE001 - a broken guard must not end a turn
                logger.exception("guard %r failed on %s", getattr(guard, "name", guard), source)
                continue
            if verdict.flagged:
                logger.info("guard %s fired on %s: %s", guard.name, source.value, verdict.rules)
                flagged.append(verdict)
        return flagged

    def _scan_results(
        self, results: tuple[ToolResult, ...]
    ) -> tuple[tuple[ToolResult, ...], list[GuardVerdict]]:
        """Sanitise tool output, keeping the cleaned text for the prompt.

        Title and url are preserved: a citation should still be clickable even
        when its page misbehaved.
        """
        cleaned: list[ToolResult] = []
        verdicts: list[GuardVerdict] = []

        for result in results:
            found = self._scan(result.snippet, ContentSource.WEB_SEARCH)
            verdicts.extend(found)
            cleaned.append(
                ToolResult(
                    tool=result.tool,
                    title=result.title,
                    url=result.url,
                    snippet=found[-1].sanitized if found else result.snippet,
                    rank=result.rank,
                )
            )
        return tuple(cleaned), verdicts

    # -- helpers ---------------------------------------------------------

    async def _should_search(
        self, mode: str, content: str, *, has_documents: bool = False
    ) -> SearchDecision:
        """Resolve the three-state mode into a decision.

        `always` still goes through here so a missing key is a no-op rather than
        an error the user has to understand.
        """
        if not self._tools or mode == "off":
            return SearchDecision(False, "search off")
        if mode == "always":
            return SearchDecision(True, "search always on")
        return await decide(content, provider=self._provider, has_documents=has_documents)

    def _estimate(self, state: TurnState) -> Usage:
        """Count tokens ourselves when the provider did not report any."""
        model = self._provider.info.model
        return Usage(
            prompt_tokens=count_message_tokens(state.prompt, model),
            completion_tokens=count_tokens(state.answer, model),
            source=UsageSource.ESTIMATED,
        )

    async def _memories_for(self, user_id: UUID) -> tuple[str, ...]:
        """Enabled facts, newest first. Never raises."""
        try:
            async with self._session_maker() as session:
                found = await MemoryService(
                    session, max_per_user=self._settings.memory_max_per_user
                ).list_for(user_id, enabled_only=True)
                return tuple(m.content for m in found)
        except Exception:  # noqa: BLE001 - losing memory degrades, never breaks
            logger.exception("could not load memories for %s", user_id)
            return ()

    async def _documents_for(self, conversation_id: UUID) -> tuple[AttachedDocument, ...]:
        """Files attached to this conversation, oldest first. Never raises."""
        try:
            async with self._session_maker() as session:
                found = await DocumentService(
                    session,
                    max_bytes=self._settings.document_max_bytes,
                    max_per_conversation=self._settings.document_max_per_conversation,
                    model=self._provider.info.model,
                ).list_for(conversation_id)
                return tuple(
                    AttachedDocument(
                        id=d.id,
                        filename=d.filename,
                        text=d.text,
                        unit=d.unit,
                        unit_count=d.unit_count,
                    )
                    for d in found
                )
        except Exception:  # noqa: BLE001 - losing a file degrades, never breaks
            logger.exception("could not load documents for %s", conversation_id)
            return ()

    async def _extract_memories(self, user_id: UUID, question: str, answer: str) -> None:
        """Propose and store new facts. Never raises, never duplicates."""
        try:
            async with self._session_maker() as session:
                service = MemoryService(
                    session, max_per_user=self._settings.memory_max_per_user
                )
                facts = await service.extract(
                    self._provider, user_message=question, assistant_message=answer
                )
                for fact in facts:
                    try:
                        await service.add(user_id, fact, source="extracted")
                    except ValidationError:
                        # Duplicate, too long, or at the limit. Skip and move on.
                        continue
                if facts:
                    logger.info("extracted %d memories for %s", len(facts), user_id)
        except Exception:  # noqa: BLE001 - extraction is best-effort
            logger.exception("memory extraction failed for %s", user_id)

    # -- persistence -----------------------------------------------------

    async def _begin_turn(
        self, user_id: UUID, conversation_id: UUID | None, content: str
    ) -> tuple[StartEvent, TurnState]:
        """Persist the question and reserve a row for the answer.

        The assistant row exists before a single token arrives so the stop
        endpoint has something to address and a reload mid-stream finds the turn
        rather than a gap.
        """
        async with self._session_maker() as session:
            repo = SqlConversationRepository(session)
            conversation = await self._resolve_conversation(
                repo, user_id, conversation_id, content
            )

            history = await repo.recent_messages(conversation.id, limit=HISTORY_MESSAGE_LIMIT)
            user_message = await repo.add_message(
                Message(conversation_id=conversation.id, role=Role.USER, content=content)
            )
            assistant_message = await repo.add_message(
                Message(
                    conversation_id=conversation.id,
                    role=Role.ASSISTANT,
                    content="",
                    model=self._provider.info.model,
                )
            )
            await repo.touch(conversation)

            start = StartEvent(
                conversation_id=conversation.id,
                user_message_id=user_message.id,
                assistant_message_id=assistant_message.id,
                title=conversation.title,
                language=conversation.language,
            )
            state = TurnState(
                question=content,
                history=tuple(
                    StoredMessage(role=Role(m.role), content=m.content) for m in history
                ),
                language=conversation.language,
            )

        return start, state

    async def _resolve_conversation(
        self,
        repo: SqlConversationRepository,
        user_id: UUID,
        conversation_id: UUID | None,
        content: str,
    ) -> Conversation:
        """Find or create the conversation, and settle its title and language."""
        if conversation_id is None:
            conversation = await repo.create(user_id, derive_title(content))
        else:
            found = await repo.get(conversation_id, user_id)
            if found is None:
                raise NotFoundError("No such conversation.")
            conversation = found
            if conversation.title == "New chat":
                conversation.title = derive_title(content)

        # Detected once, from the first message, then reused. Re-detecting every
        # turn would make the reply language flip on a short "ok".
        if conversation.language is None:
            conversation.language = detect_language(
                content,
                supported=list(self._settings.supported_languages),
                default=self._settings.default_language,
            )
            logger.info(
                "conversation %s detected as %s", conversation.id, conversation.language
            )
        return conversation

    async def _begin_regeneration(
        self, user_id: UUID, assistant_message_id: UUID
    ) -> tuple[StartEvent, TurnState]:
        """Clear an assistant message and re-answer the question above it.

        Only the most recent answer can be regenerated. Redoing an earlier one
        would orphan every exchange after it, and silently deleting a
        conversation's tail is not something a button should do.
        """
        async with self._session_maker() as session:
            repo = SqlConversationRepository(session)
            target = await repo.get_message(assistant_message_id)
            if target is None or target.role != Role.ASSISTANT:
                raise NotFoundError("No such message.")

            conversation = await repo.get(target.conversation_id, user_id)
            if conversation is None:
                raise NotFoundError("No such message.")

            ordered = conversation.messages
            if not ordered or ordered[-1].id != target.id:
                raise ValidationError("Only the latest response can be regenerated.")
            if len(ordered) < 2 or ordered[-2].role != Role.USER:
                raise ValidationError("There is no question to answer again.")

            question = ordered[-2].content
            history = tuple(
                StoredMessage(role=Role(m.role), content=m.content) for m in ordered[:-2]
            )

            # Reuse the row so its id stays stable for anything referencing it.
            target.content = ""
            target.finish_reason = None
            target.model = self._provider.info.model
            await repo.touch(conversation)

            start = StartEvent(
                conversation_id=conversation.id,
                user_message_id=ordered[-2].id,
                assistant_message_id=target.id,
                title=conversation.title,
                language=conversation.language,
            )
            state = TurnState(
                question=question, history=history, language=conversation.language
            )

        return start, state


def _summarise(count: int, noun: str, started: float) -> str:
    """"5 results in 1.2s" — the count alone does not say whether the wait was
    the search or the model, which is the question when a turn feels slow."""
    plural = "" if count == 1 else "s"
    return f"{count} {noun}{plural} in {perf_counter() - started:.1f}s"


async def list_conversations(
    session: AsyncSession, user_id: UUID, *, limit: int, offset: int
) -> tuple[list[Conversation], int]:
    repo = SqlConversationRepository(session)
    return (
        await repo.list_for_user(user_id, limit=limit, offset=offset),
        await repo.count_for_user(user_id),
    )

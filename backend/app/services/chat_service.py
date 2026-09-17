"""The chat turn.

Orchestrates: persist the question, assemble the prompt from context
contributors, stream the answer, and persist whatever arrived — including when
the user stops it half way.

Transactions are short and explicit. A streaming response can stay open for
minutes, and holding a database transaction open for that long would pin a
connection and block migrations for as long as someone is reading an answer.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.context.base import ContextContributor, StoredMessage, TurnContext
from app.context.pipeline import build_messages
from app.core.errors import NotFoundError, ValidationError
from app.core.tokens import count_message_tokens, count_tokens
from app.db.models.conversation import Conversation, Message
from app.db.models.source import MessageSource
from app.db.repositories.conversations import SqlConversationRepository
from app.guards.base import ContentSource, Guard, GuardVerdict
from app.providers.base import (
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
from app.services.language_service import detect_language
from app.services.memory_service import MemoryService
from app.services.search_intent import SearchDecision, decide
from app.services.suggestion_service import suggest
from app.tools.serpapi import SearchProvider, SearchUnavailable

logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 32_000
HISTORY_MESSAGE_LIMIT = 50
TITLE_MAX_LENGTH = 60

SessionMaker = Callable[[], AbstractAsyncContextManager[AsyncSession]]
# Built per turn rather than once, because the memory contributor needs this
# user's facts and those change between requests.
ContributorFactory = Callable[[tuple[str, ...]], tuple[ContextContributor, ...]]


# --- events surfaced to the API layer -----------------------------------


@dataclass(frozen=True, slots=True)
class StartEvent:
    conversation_id: UUID
    user_message_id: UUID
    assistant_message_id: UUID
    title: str
    language: str | None = None


@dataclass(frozen=True, slots=True)
class DeltaEvent:
    text: str


@dataclass(frozen=True, slots=True)
class ToolEvent:
    """Progress of a tool, so the UI can say what is happening and why the
    first token is taking a moment."""

    tool: str
    status: str  # running | done | failed
    label: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class GuardEventPayload:
    """A guard fired. Surfaced so the banner can explain itself rather than
    silently altering what the model sees."""

    source: str
    severity: str
    rules: tuple[str, ...]
    evidence: str


@dataclass(frozen=True, slots=True)
class SourcesEvent:
    sources: tuple[ToolResult, ...]


@dataclass(frozen=True, slots=True)
class AccountingEvent:
    accounting: Accounting


@dataclass(frozen=True, slots=True)
class SuggestionsEvent:
    items: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DoneEvent:
    finish_reason: FinishReason


@dataclass(frozen=True, slots=True)
class ErrorEvent:
    message: str


ChatEvent = (
    StartEvent
    | ToolEvent
    | GuardEventPayload
    | SourcesEvent
    | DeltaEvent
    | AccountingEvent
    | SuggestionsEvent
    | DoneEvent
    | ErrorEvent
)


def _guard_payload(verdict: GuardVerdict) -> GuardEventPayload:
    return GuardEventPayload(
        source=str(verdict.source),
        severity=verdict.severity.label,
        rules=verdict.rules,
        evidence=verdict.findings[0].evidence if verdict.findings else "",
    )


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
        budget: TokenBudget,
        max_tokens: int,
        temperature: float,
        pricing: Pricing,
        supported_languages: list[str],
        default_language: str,
        search: SearchProvider | None = None,
        search_limit: int = 5,
        guards: tuple[Guard, ...] = (),
        suggestions_enabled: bool = True,
        suggestions_count: int = 3,
        memory_auto_extract: bool = True,
        memory_max_per_user: int = 100,
    ) -> None:
        self._session_maker = session_maker
        self._provider = provider
        self._build_contributors = contributor_factory
        self._cancellation = cancellation
        self._budget = budget
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._pricing = pricing
        self._supported_languages = supported_languages
        self._default_language = default_language
        self._search = search
        self._search_limit = search_limit
        self._guards = guards
        self._suggestions_enabled = suggestions_enabled
        self._suggestions_count = suggestions_count
        self._memory_auto_extract = memory_auto_extract
        self._memory_max_per_user = memory_max_per_user

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
        if regenerate_of is None:
            content = content.strip()
            if not content:
                raise ValidationError("Message cannot be empty.")
            if len(content) > MAX_MESSAGE_LENGTH:
                raise ValidationError(
                    f"Message is too long ({len(content)} characters, "
                    f"limit {MAX_MESSAGE_LENGTH})."
                )
            start, history = await self._begin_turn(user_id, conversation_id, content)
        else:
            start, history, content = await self._begin_regeneration(user_id, regenerate_of)
        yield start

        assistant_id = start.assistant_message_id
        cancel = self._cancellation.register(assistant_id)
        collected: list[str] = []
        finish = FinishReason.STOP
        error: str | None = None
        usage: Usage | None = None
        request_messages: tuple = ()
        tool_results: tuple[ToolResult, ...] = ()

        try:
            for verdict in self._scan(content, ContentSource.USER_INPUT):
                yield _guard_payload(verdict)

            tool_results: tuple[ToolResult, ...] = ()
            decision = await self._should_search(search_mode, content)
            if decision.needs_search and self._search is not None:
                yield ToolEvent(
                    tool=self._search.name,
                    status="running",
                    label="Searching the web",
                    detail=decision.reason,
                )
                try:
                    found = await self._search.search(content, limit=self._search_limit)
                    # Scanned before the contributor sees them. Retrieved pages
                    # are the realistic injection vector: nobody asked that page
                    # for instructions.
                    tool_results, verdicts = self._scan_results(found)
                    for verdict in verdicts:
                        yield _guard_payload(verdict)
                    yield ToolEvent(
                        tool=self._search.name,
                        status="done",
                        label="Searched the web",
                        detail=f"{len(found)} result{'' if len(found) == 1 else 's'}",
                    )
                    if tool_results:
                        yield SourcesEvent(sources=tool_results)
                except SearchUnavailable as exc:
                    # A failed search degrades the answer; it does not end the
                    # turn. The model answers from what it knows and the UI says
                    # search did not run.
                    logger.info("search unavailable: %s", exc)
                    yield ToolEvent(
                        tool=self._search.name,
                        status="failed",
                        label="Search unavailable",
                        detail=str(exc),
                    )

            turn = TurnContext(
                conversation_id=start.conversation_id,
                user_id=user_id,
                user_message=content,
                model=self._provider.info.model,
                history=history,
                budget=self._budget,
                language=start.language,
                tool_results=tool_results,
            )
            memories = await self._memories_for(user_id)
            messages, trace = await build_messages(turn, self._build_contributors(memories))
            request_messages = messages
            logger.info("prompt assembled for %s: %s", assistant_id, trace.as_dict())

            request = ChatRequest(
                messages=messages,
                model=self._provider.info.model,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
                stream=True,
            )

            async for event in self._provider.stream_chat(request):
                if cancel.is_set():
                    finish = FinishReason.STOPPED
                    break
                if isinstance(event, TokenEvent):
                    collected.append(event.text)
                    yield DeltaEvent(text=event.text)
                elif isinstance(event, ProviderUsageEvent):
                    usage = event.usage

        except ProviderError as exc:
            finish = FinishReason.ERROR
            error = exc.message
            logger.warning("provider failed during turn %s: %s", assistant_id, exc.message)
        except Exception:
            finish = FinishReason.ERROR
            error = "Something went wrong generating the response."
            logger.exception("unexpected failure during turn %s", assistant_id)
        finally:
            self._cancellation.release(assistant_id)
            # A cancelled or failed turn still consumed tokens, so it is still
            # priced. Usage the provider never sent is estimated instead.
            accounting = price(
                usage or self._estimate(request_messages, collected), self._pricing
            )
            # Persist whatever arrived, even on error or cancellation. A partial
            # answer the user watched appear should still be there on reload.
            await self._finish_turn(
                assistant_id, "".join(collected), finish, accounting, tool_results
            )

        yield AccountingEvent(accounting=accounting)

        answer = "".join(collected)
        # Only after a clean finish. Suggesting follow-ups to a half-written or
        # failed answer wastes a call and reads as the app not noticing.
        if self._suggestions_enabled and finish is FinishReason.STOP and answer.strip():
            items = await suggest(
                self._provider,
                user_message=content,
                assistant_message=answer,
                count=self._suggestions_count,
            )
            if items:
                yield SuggestionsEvent(items=tuple(items))

        if self._memory_auto_extract and finish is FinishReason.STOP and answer.strip():
            await self._extract_memories(user_id, content, answer)

        if error is not None:
            yield ErrorEvent(message=error)
        yield DoneEvent(finish_reason=finish)

    async def stop(self, *, user_id: UUID, message_id: UUID) -> bool:
        """Cancel an in-flight response. Ownership is checked first."""
        async with self._session_maker() as session:
            repo = SqlConversationRepository(session)
            message = await repo.get_message(message_id)
            if message is None:
                raise NotFoundError("No such message.")
            conversation = await repo.get(message.conversation_id, user_id)
            if conversation is None:
                raise NotFoundError("No such message.")
        return self._cancellation.cancel(message_id)

    # -- internals -------------------------------------------------------

    async def _should_search(self, mode: str, content: str) -> SearchDecision:
        """Resolve the three-state mode into a yes or no.

        `always` still goes through here so that a missing SERPAPI_KEY is a
        no-op rather than an error the user has to understand.
        """
        if self._search is None or mode == "off":
            return SearchDecision(False, "search off")
        if mode == "always":
            return SearchDecision(True, "search always on")
        return await decide(content, provider=self._provider)

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
                logger.info(
                    "guard %s fired on %s: %s", guard.name, source.value, verdict.rules
                )
                flagged.append(verdict)
        return flagged

    def _scan_results(
        self, results: list[ToolResult]
    ) -> tuple[tuple[ToolResult, ...], list[GuardVerdict]]:
        """Sanitise tool output, keeping the cleaned text for the prompt.

        The original title and url are preserved for the source list — a
        citation should still be clickable even when its page misbehaved.
        """
        cleaned: list[ToolResult] = []
        verdicts: list[GuardVerdict] = []

        for result in results:
            found = self._scan(result.snippet, ContentSource.WEB_SEARCH)
            snippet = result.snippet
            for verdict in found:
                snippet = verdict.sanitized
            verdicts.extend(found)
            cleaned.append(
                ToolResult(
                    tool=result.tool,
                    title=result.title,
                    url=result.url,
                    snippet=snippet,
                    rank=result.rank,
                )
            )
        return tuple(cleaned), verdicts

    async def _memories_for(self, user_id: UUID) -> tuple[str, ...]:
        """Enabled facts, newest first. Never raises."""
        try:
            async with self._session_maker() as session:
                service = MemoryService(session, max_per_user=self._memory_max_per_user)
                found = await service.list_for(user_id, enabled_only=True)
                return tuple(m.content for m in found)
        except Exception:  # noqa: BLE001 - losing memory degrades, never breaks
            logger.exception("could not load memories for %s", user_id)
            return ()

    async def _extract_memories(self, user_id: UUID, question: str, answer: str) -> None:
        """Propose and store new facts. Never raises, never duplicates."""
        try:
            async with self._session_maker() as session:
                service = MemoryService(session, max_per_user=self._memory_max_per_user)
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

    def _estimate(self, messages: tuple, collected: list[str]) -> Usage:
        """Count tokens ourselves when the provider did not report any."""
        return Usage(
            prompt_tokens=count_message_tokens(messages, self._provider.info.model),
            completion_tokens=count_tokens("".join(collected), self._provider.info.model),
            source=UsageSource.ESTIMATED,
        )

    async def _begin_turn(
        self, user_id: UUID, conversation_id: UUID | None, content: str
    ) -> tuple[StartEvent, tuple[StoredMessage, ...]]:
        """Persist the question and reserve a row for the answer.

        The assistant row exists before a single token arrives so the stop
        endpoint has something to address and a reload mid-stream finds the
        turn rather than a gap.
        """
        async with self._session_maker() as session:
            repo = SqlConversationRepository(session)

            if conversation_id is None:
                conversation = await repo.create(user_id, derive_title(content))
            else:
                found = await repo.get(conversation_id, user_id)
                if found is None:
                    raise NotFoundError("No such conversation.")
                conversation = found
                if conversation.title == "New chat":
                    conversation.title = derive_title(content)

            # Detected once, from the first message, then reused. Re-detecting
            # every turn would make the reply language flip on a short "ok".
            if conversation.language is None:
                conversation.language = detect_language(
                    content,
                    supported=self._supported_languages,
                    default=self._default_language,
                )
                logger.info(
                    "conversation %s detected as %s", conversation.id, conversation.language
                )

            history = await repo.recent_messages(
                conversation.id, limit=HISTORY_MESSAGE_LIMIT
            )

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
            stored = tuple(
                StoredMessage(role=Role(m.role), content=m.content) for m in history
            )

        return start, stored

    async def _begin_regeneration(
        self, user_id: UUID, assistant_message_id: UUID
    ) -> tuple[StartEvent, tuple[StoredMessage, ...], str]:
        """Clear an assistant message and re-answer the question above it.

        Only the most recent assistant message can be regenerated. Regenerating
        an earlier one would orphan every exchange after it, and silently
        deleting a conversation's tail is not something a button should do.
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

        return start, history, question

    async def _finish_turn(
        self,
        assistant_id: UUID,
        content: str,
        finish: FinishReason,
        accounting: Accounting,
        sources: tuple[ToolResult, ...] = (),
    ) -> None:
        async with self._session_maker() as session:
            repo = SqlConversationRepository(session)
            message = await repo.get_message(assistant_id)
            if message is None:  # pragma: no cover - only if deleted mid-stream
                logger.warning("assistant message %s vanished before persist", assistant_id)
                return
            message.content = content
            message.finish_reason = finish
            message.prompt_tokens = accounting.prompt_tokens
            message.completion_tokens = accounting.completion_tokens
            message.cost = accounting.cost
            message.usage_source = str(accounting.source)

            if sources:
                # Replaced wholesale, so regenerating with search on does not
                # accumulate citations from the previous attempt.
                message.sources = [
                    MessageSource(
                        message_id=message.id,
                        tool=source.tool,
                        title=source.title[:500],
                        url=source.url,
                        snippet=source.snippet,
                        rank=source.rank,
                    )
                    for source in sources
                ]


async def list_conversations(
    session: AsyncSession, user_id: UUID, *, limit: int, offset: int
) -> tuple[list[Conversation], int]:
    repo = SqlConversationRepository(session)
    return (
        await repo.list_for_user(user_id, limit=limit, offset=offset),
        await repo.count_for_user(user_id),
    )

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

import json
import logging
from asyncio import Event
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field, replace
from datetime import datetime
from time import perf_counter
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.artifacts.base import Built, DesignSpec, OpenArtifact
from app.context.base import (
    AttachedDocument,
    ContextContributor,
    StoredMessage,
    TurnContext,
)
from app.context.contributors import format_results, images_already_shown
from app.context.pipeline import build_messages
from app.core.clock import Clock, now_in, utc_now
from app.core.errors import NotFoundError, ValidationError
from app.core.tokens import count_message_tokens, count_tokens
from app.db.models.conversation import Conversation, Message
from app.db.models.source import MessageSource
from app.db.repositories.artifacts import SqlArtifactRepository
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
    ToolCall,
    ToolCallsEvent,
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
    ArtifactDeltaEvent,
    ArtifactDesignEvent,
    ArtifactDoneEvent,
    ArtifactFailedEvent,
    ArtifactPartEvent,
    ArtifactPlanEvent,
    ArtifactStartEvent,
    ArtifactStepEvent,
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
from app.tools.base import (
    ArtifactAwareTool,
    Drafting,
    Looks,
    Made,
    Making,
    Piece,
    Planned,
    Progress,
    ProgressiveTool,
    Results,
    SearchingTool,
    Tool,
    ToolUnavailable,
    ToolUpdate,
    bind_arguments,
    missing_arguments,
    tool_schema,
)

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
    tool_calling_enabled: bool = True
    tool_max_iterations: int = 3
    # For a request that does not say where the person is.
    default_timezone: str = "UTC"


@dataclass(slots=True)
class TurnState:
    """What the turn accumulates as it runs.

    The one mutable thing in the flow, on purpose: everything crossing a
    boundary is frozen, and this is the accumulator the phases write into.
    """

    question: str
    # When this turn is happening, in the person's zone: the one moment the
    # prompt and every set of results in it are dated by.
    now: datetime | None = None
    conversation_id: UUID | None = None
    user_id: UUID | None = None
    assistant_id: UUID | None = None
    # What the person is looking at while they type. Without it, "make it
    # warmer" has no subject.
    open_artifact: OpenArtifact | None = None
    history: tuple[StoredMessage, ...] = ()
    language: str | None = None
    tool_results: tuple[ToolResult, ...] = ()
    image_results: tuple[ToolResult, ...] = ()
    prompt: tuple[ChatMessage, ...] = ()
    chunks: list[str] = field(default_factory=list)
    usage: Usage | None = None
    finish: FinishReason = FinishReason.STOP
    error: str | None = None
    # The tools this turn offered the model, if any. Empty means the turn chose
    # for itself — the fallback when tool calling is off or unsupported.
    offered: dict[str, Tool] = field(default_factory=dict)
    # Search mode "always" means always, so the model is told it must call
    # something rather than invited to consider it.
    force_tool: bool = False
    # Assistant tool-call requests and their results, appended after the built
    # prompt. This is the conversation the model is having with the tools, and
    # it has to be replayed on every iteration or the model loses what it asked.
    exchange: list[ChatMessage] = field(default_factory=list)

    @property
    def answer(self) -> str:
        return "".join(self.chunks)

    def add_usage(self, usage: Usage) -> None:
        """Sum, never replace: a turn that called two tools paid for three
        model calls, and reporting only the last one prices it as a third of
        what it cost.

        Mixing a measured count with an estimated one degrades the whole turn to
        estimated, for the same reason `usage_source` exists at all.
        """
        if self.usage is None:
            self.usage = usage
            return
        self.usage = Usage(
            prompt_tokens=self.usage.prompt_tokens + usage.prompt_tokens,
            completion_tokens=self.usage.completion_tokens + usage.completion_tokens,
            source=self.usage.source
            if self.usage.source == usage.source
            else UsageSource.ESTIMATED,
        )

    def absorb(self, results: tuple[ToolResult, ...]) -> tuple[ToolResult, ...]:
        """Add results to the turn, renumbered to follow what is already there.

        Two searches in one turn both come back numbered from 1, and duplicate
        citation markers make `[2]` mean two different pages in one answer.
        """
        start = len(self.tool_results)
        renumbered = tuple(
            replace(result, rank=start + offset) for offset, result in enumerate(results, 1)
        )
        self.tool_results = (*self.tool_results, *renumbered)
        return renumbered

    @property
    def citations(self) -> tuple[ToolResult, ...]:
        return (*self.tool_results, *self.image_results)


def _parse_arguments(raw: str) -> dict[str, object] | None:
    """The model's arguments, or None when they are not a JSON object.

    Returning None rather than raising: a malformed call is something the model
    can be told about and retry, not a failed turn.
    """
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


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
        clock: Clock = utc_now,
    ) -> None:
        self._clock = clock
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
        artifact_id: UUID | None = None,
        timezone: str | None = None,
    ) -> AsyncIterator[ChatEvent]:
        start, state = await self._open(user_id, conversation_id, content, regenerate_of)
        state.now = now_in(timezone, default=self._settings.default_timezone, clock=self._clock)
        # Where this turn is happening, so anything it makes can be stored
        # against the right conversation and the right answer.
        state.conversation_id = start.conversation_id
        state.user_id = user_id
        state.assistant_id = start.assistant_message_id
        state.open_artifact = await self._open_artifact(artifact_id, user_id)
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
        """Guards, then tools — but only the ones the model cannot ask for.

        When the model can choose, this phase deliberately runs nothing: the
        choice belongs inside `_generate`, where the answer and the tool calls
        are the same conversation.
        """
        for verdict in self._scan(state.question, ContentSource.USER_INPUT):
            yield guard_payload(verdict)

        state.offered = self._tools_to_offer(state, search_mode)
        if state.offered:
            # Forced only when the person asked for search on every message,
            # and only if there is something to search with. Forcing a call
            # with only a make-something tool on the table would have it make
            # something nobody asked for.
            state.force_tool = search_mode == "always" and any(
                _searches(tool) for tool in state.offered.values()
            )
            return

        if search_mode == "off":
            return

        decision = await self._should_search(
            search_mode, state.question, has_documents=has_documents
        )
        tool = self._select_tool(decision)
        if tool is None:
            return

        async for event in self._run_tool(
            tool, state, arguments={"query": state.question}, detail=decision.reason
        ):
            yield event

    async def _open_artifact(
        self, artifact_id: UUID | None, user_id: UUID
    ) -> OpenArtifact | None:
        """Whatever the panel is showing, if anything.

        Wrapped: an artifact that cannot be loaded costs the turn its subject,
        not the turn itself.
        """
        if artifact_id is None:
            return None
        try:
            async with self._session_maker() as session:
                repo = SqlArtifactRepository(session)
                artifact = await repo.get(artifact_id, user_id)
                if artifact is None:
                    return None
                current = await repo.version(artifact)
                if current is None:
                    return None
                return OpenArtifact(
                    id=artifact.id,
                    kind=artifact.kind,
                    title=artifact.title,
                    html=current.html,
                    spec=DesignSpec.from_dict(current.design_spec or {}),
                )
        except Exception:  # noqa: BLE001 - a missing subject is not a failed turn
            logger.exception("could not load the open artifact %s", artifact_id)
            return None

    def _tools_to_offer(self, state: TurnState, search_mode: str = "auto") -> dict[str, Tool]:
        """The tools this turn hands the model, or nothing.

        Nothing means the turn falls back to `_select_tool` — which keeps search
        working on a provider that cannot do function calling, instead of
        quietly losing it.
        """
        if not self._tools or not self._settings.tool_calling_enabled:
            return {}
        if not self._provider.info.supports_tools:
            return {}
        # Re-keyed by the tool's own name, which is what the schema advertises
        # and therefore what the model calls back with. The registry's key is
        # usually the same string, but dispatch must not depend on that.
        #
        # A tool that acts on the open artifact is withheld when there is none:
        # offering a way to change nothing invites the model to try. Searching
        # is withheld when the person turned search off — and only searching,
        # because "off" was never meant to mean "and do not make anything
        # either".
        return {
            tool.name: tool
            for tool in self._tools.values()
            if (state.open_artifact is not None or not _needs_open_artifact(tool))
            and not (search_mode == "off" and _searches(tool))
        }

    def _select_tool(self, decision: SearchDecision) -> Tool | None:
        """Choosing a tool from the question, for providers that cannot choose.

        Kept as the fallback rather than deleted: a local Ollama build with no
        function calling should still search, and a template that only works
        against the big providers is not much of a template.
        """
        if not decision.needs_search:
            return None
        return self._tools.get("image_search" if decision.wants_images else "web_search")

    async def _run_tool(
        self,
        tool: Tool,
        state: TurnState,
        *,
        arguments: dict[str, Any],
        detail: str,
        sink: list[str] | None = None,
    ) -> AsyncIterator[ChatEvent]:
        """Run one tool, reporting it, and record what it found.

        `sink`, when given, receives the text the model should read next. That
        is how a model-requested call gets its answer: the same results the UI
        renders, worded for a tool message.
        """
        yield ToolEvent(
            tool=tool.name,
            status="running",
            label=tool.presentation.running,
            detail=detail,
        )

        started = perf_counter()
        found = 0
        made = 0
        making = False
        try:
            async for update in _updates(tool, arguments):
                if isinstance(update, Making):
                    making = True
                    yield ArtifactStartEvent(kind=update.kind, title=update.title)
                    continue
                if isinstance(update, Progress):
                    # Only a build has steps worth naming on the panel. A tool
                    # that merely narrates keeps its chip and nothing more.
                    if making:
                        yield ArtifactStepEvent(label=update.label, detail=update.detail)
                    yield ToolEvent(
                        tool=tool.name,
                        status="running",
                        label=update.label,
                        detail=update.detail,
                    )
                    continue
                if isinstance(update, Drafting):
                    yield ArtifactDeltaEvent(text=update.text)
                    continue
                if isinstance(update, Looks):
                    yield ArtifactDesignEvent(
                        movement=update.movement,
                        palette=update.palette,
                        display_font=update.display_font,
                        body_font=update.body_font,
                        rationale=update.rationale,
                        width=update.width,
                        height=update.height,
                    )
                    continue
                if isinstance(update, Planned):
                    yield ArtifactPlanEvent(titles=update.titles)
                    continue
                if isinstance(update, Piece):
                    yield ArtifactPartEvent(
                        index=update.index,
                        total=update.total,
                        title=update.title,
                        html=update.html,
                    )
                    continue
                if isinstance(update, Made):
                    made += 1
                    async for event in self._keep(state, update, sink):
                        yield event
                    continue
                found += len(update.items)
                for event in self._record(state, update.items, sink):
                    yield event
        except ToolUnavailable as exc:
            # A failed tool degrades the answer; it does not end the turn. The
            # model answers from what it knows and the UI says what was missed.
            logger.info("tool %s unavailable: %s", tool.name, exc)
            if making:
                # The panel is showing a build. Without this it keeps showing
                # it — a spinner on a step that will never finish, which is how
                # a failed change reads as a hung one.
                yield ArtifactFailedEvent(message=str(exc), retryable=True)
            yield ToolEvent(
                tool=tool.name,
                status="failed",
                label=tool.presentation.failed,
                detail=str(exc),
            )
            if sink is not None:
                sink.append(f"The {tool.name} tool is unavailable: {exc}")
            return

        yield ToolEvent(
            tool=tool.name,
            status="done",
            label=tool.presentation.done,
            detail=_summarise(made or found, tool.presentation.noun, started),
        )

    async def _keep(
        self, state: TurnState, made: Made, sink: list[str] | None
    ) -> AsyncIterator[ChatEvent]:
        """Store what a tool made, and tell the panel where to find it.

        Saved here rather than in the tool: a tool has no business holding a
        session, and this is the one place that knows which conversation and
        which answer it belongs to.
        """
        if state.conversation_id is None or state.user_id is None:
            # Nothing to attach it to. Only reachable from a test that drives
            # the phase directly.
            return

        built = made.built
        async with self._session_maker() as session:
            repo = SqlArtifactRepository(session)
            if made.replaces is not None:
                # A change to something that exists is its next version, not a
                # second artifact competing for the same panel.
                existing = await repo.get(made.replaces, state.user_id)
                if existing is not None:
                    version = await repo.add_version(
                        existing,
                        html=built.html,
                        design_spec=built.spec.as_dict(),
                        model=built.model,
                        prompt_tokens=built.prompt_tokens,
                        completion_tokens=built.completion_tokens,
                        build_ms=built.build_ms,
                    )
                    await session.commit()
                    yield ArtifactDoneEvent(
                        artifact_id=existing.id,
                        kind=made.kind,
                        title=made.title,
                        version=version.version,
                        size_bytes=len(built.html.encode()),
                        width=built.spec.width,
                        height=built.spec.height,
                        findings=built.findings,
                    )
                    if sink is not None:
                        sink.append(
                            f"The {made.kind} has been changed and the new version is on "
                            "screen. Say in one line what changed. Do not describe the "
                            "markup."
                            + _caveats(built.note)
                        )
                    return

            artifact = await repo.create(
                conversation_id=state.conversation_id,
                user_id=state.user_id,
                message_id=state.assistant_id,
                kind=made.kind,
                title=made.title,
                html=built.html,
                design_spec=built.spec.as_dict(),
                model=built.model,
                prompt_tokens=built.prompt_tokens,
                completion_tokens=built.completion_tokens,
                build_ms=built.build_ms,
            )
            await session.commit()
            artifact_id, version = artifact.id, artifact.current_version

        yield ArtifactDoneEvent(
            artifact_id=artifact_id,
            kind=made.kind,
            title=made.title,
            version=version,
            size_bytes=len(built.html.encode()),
            width=built.spec.width,
            height=built.spec.height,
            findings=built.findings,
        )
        if sink is not None:
            # What the model reads next. It must not be the document: the
            # person can see it, and replaying thousands of tokens of CSS into
            # the next request buys nothing and costs everything.
            sink.append(
                f"The {made.kind} \"{made.title}\" is made and is on screen next to "
                "the conversation. Tell them briefly what you made and what they "
                "can change. Do not describe the markup and do not repeat the text "
                "on it." + _facts(built) + _caveats(built.note)
            )

    def _record(
        self, state: TurnState, found: tuple[ToolResult, ...], sink: list[str] | None
    ) -> Iterator[ChatEvent]:
        """Take one batch of results into the turn.

        Pictures and pages are told apart by shape — a result carrying a
        thumbnail is one — so a new tool returning images gets the grid without
        naming itself anywhere.
        """
        if not found:
            if sink is not None:
                sink.append("The search returned no usable results.")
            return

        if any(result.is_image for result in found):
            state.image_results = (*state.image_results, *found)
            yield ImagesEvent(images=found)
            if sink is not None:
                sink.append(images_already_shown(found))
            return

        # Retrieved pages are the realistic injection vector: nobody asked that
        # page for instructions. Scanned before any contributor sees them.
        scanned, verdicts = self._scan_results(found)
        for verdict in verdicts:
            yield guard_payload(verdict)
        added = state.absorb(scanned)
        if added:
            yield SourcesEvent(sources=added)
        if sink is not None:
            sink.append(
                format_results(
                    added,
                    model=self._provider.info.model,
                    budget=self._settings.budget.tools,
                    now=state.now,
                )
                if added
                else "The search returned no usable results."
            )

    # -- phase 3: generate -----------------------------------------------

    async def _generate(
        self,
        state: TurnState,
        start: StartEvent,
        user_id: UUID,
        cancel: Event,
        documents: tuple[AttachedDocument, ...],
    ) -> AsyncIterator[ChatEvent]:
        """Stream the answer, running whatever tools the model asks for first.

        One loop, not a special case: without tool calling `remaining` starts at
        zero, nothing is offered, and this is a single streamed pass — exactly
        what it was before.
        """
        memories = await self._memories_for(user_id)
        remaining = self._settings.tool_max_iterations if state.offered else 0

        while True:
            # Offered only while there is budget to act on an answer. On the
            # last pass the model gets no tools, so it has to reply with words.
            offered = state.offered if remaining > 0 else {}
            state.prompt = await self._assemble(state, start, user_id, memories, documents)

            calls: list[ToolCall] = []
            async for event in self._stream_once(state, offered, cancel, calls):
                yield event

            if cancel.is_set() or not calls:
                return

            async for event in self._dispatch(state, offered, tuple(calls)):
                yield event
            # Forced once. Leaving it on would make the model call again
            # forever instead of answering from what it just got.
            state.force_tool = False
            remaining -= 1

    async def _assemble(
        self,
        state: TurnState,
        start: StartEvent,
        user_id: UUID,
        memories: tuple[str, ...],
        documents: tuple[AttachedDocument, ...],
    ) -> tuple[ChatMessage, ...]:
        """Build the prompt, then append the tool conversation so far.

        `tool_results` is withheld from the context when the model is choosing:
        the results are already in the exchange as tool messages, which is where
        the protocol puts them, and passing both would send every page twice.
        """
        turn = TurnContext(
            conversation_id=start.conversation_id,
            user_id=user_id,
            user_message=state.question,
            model=self._provider.info.model,
            history=state.history,
            budget=self._settings.budget,
            language=state.language,
            tool_results=() if state.offered else state.citations,
            documents=documents,
            now=state.now,
        )
        built, trace = await build_messages(turn, self._build_contributors(memories))
        logger.info("prompt assembled for %s: %s", start.assistant_message_id, trace.as_dict())
        return (*built, *state.exchange)

    async def _stream_once(
        self,
        state: TurnState,
        offered: dict[str, Tool],
        cancel: Event,
        calls: list[ToolCall],
    ) -> AsyncIterator[ChatEvent]:
        """One streamed model call. Collects any tool requests into `calls`."""
        request = ChatRequest(
            messages=state.prompt,
            model=self._provider.info.model,
            temperature=self._settings.temperature,
            max_tokens=self._settings.max_tokens,
            stream=True,
            tools=tuple(tool_schema(tool) for tool in offered.values()),
            tool_choice=("required" if state.force_tool else "auto") if offered else None,
        )

        async for event in self._provider.stream_chat(request):
            if cancel.is_set():
                state.finish = FinishReason.STOPPED
                return
            if isinstance(event, TokenEvent):
                state.chunks.append(event.text)
                yield DeltaEvent(text=event.text)
            elif isinstance(event, ProviderUsageEvent):
                state.add_usage(event.usage)
            elif isinstance(event, ToolCallsEvent) and offered:
                calls.extend(event.calls)
            elif isinstance(event, ToolCallsEvent):
                # Asked for a tool that was not on the table. Ignored rather
                # than run, because honouring it would make the iteration cap
                # advisory — a provider that always calls something could loop
                # for as long as it liked.
                logger.info("ignoring %d tool call(s) offered no tools", len(event.calls))

    async def _dispatch(
        self, state: TurnState, offered: dict[str, Tool], calls: tuple[ToolCall, ...]
    ) -> AsyncIterator[ChatEvent]:
        """Run the tools the model asked for and record the exchange.

        Every branch appends a tool message, including the failures. A
        `tool_calls` request with an unanswered id is a protocol error at the
        next request, so "I could not do that" has to be said in the exchange
        rather than only in the log.
        """
        state.exchange.append(ChatMessage(role=Role.ASSISTANT, content="", tool_calls=calls))

        for call in calls:
            tool = offered.get(call.name)
            if tool is None:
                logger.info("model asked for unknown tool %r", call.name)
                yield ToolEvent(
                    tool=call.name,
                    status="failed",
                    label="Unknown tool",
                    detail=f"{call.name} is not available",
                )
                self._answer_call(state, call, f"There is no tool named {call.name}.")
                continue

            arguments = _parse_arguments(call.arguments)
            if arguments is None:
                yield ToolEvent(
                    tool=tool.name,
                    status="failed",
                    label="Could not read the request",
                    detail="the arguments were not valid JSON",
                )
                self._answer_call(
                    state, call, "Those arguments were not valid JSON. Try again."
                )
                continue

            bound = bind_arguments(tool, arguments)
            missing = missing_arguments(tool, bound)
            if missing:
                named = ", ".join(missing)
                yield ToolEvent(
                    tool=tool.name,
                    status="failed",
                    label="Nothing to look up",
                    detail=f"missing {named}",
                )
                self._answer_call(state, call, f"Missing required argument: {named}.")
                continue

            said = _asked_for(bound)
            if _needs_open_artifact(tool) and state.open_artifact is not None:
                # Handed in rather than looked up: the tool asks for the open
                # artifact by declaring it wants one, and never learns how to
                # find it.
                bound["open_artifact"] = state.open_artifact

            sink: list[str] = []
            # `detail` is what the model chose to look up, which tells the user
            # more than a regex's reason ever did.
            async for event in self._run_tool(
                tool, state, arguments=bound, detail=said, sink=sink
            ):
                yield event
            self._answer_call(state, call, "\n\n".join(sink))

    def _answer_call(self, state: TurnState, call: ToolCall, content: str) -> None:
        state.exchange.append(
            ChatMessage(role=Role.TOOL, content=content or "No result.", tool_call_id=call.id)
        )

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
        when its page misbehaved. What was read from the page is scanned like
        the snippet: nobody asked that page for instructions, and there is far
        more of it than two lines.
        """
        cleaned: list[ToolResult] = []
        verdicts: list[GuardVerdict] = []

        for result in results:
            in_snippet = self._scan(result.snippet, ContentSource.WEB_SEARCH)
            in_page = self._scan(result.excerpt, ContentSource.WEB_SEARCH) if result.excerpt else []
            verdicts.extend((*in_snippet, *in_page))
            cleaned.append(
                replace(
                    result,
                    snippet=in_snippet[-1].sanitized if in_snippet else result.snippet,
                    excerpt=in_page[-1].sanitized if in_page else result.excerpt,
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

    async def _attach_pending_documents(
        self, session: AsyncSession, conversation_id: UUID, message_id: UUID
    ) -> None:
        """Bind unsent files to the message being sent. Never raises.

        A file that fails to bind is still readable — the contributor loads by
        conversation — so the only loss is the card in the transcript. Not worth
        failing a turn over.
        """
        try:
            bound = await DocumentService(
                session,
                max_bytes=self._settings.document_max_bytes,
                max_per_conversation=self._settings.document_max_per_conversation,
                model=self._provider.info.model,
            ).attach_to_message(conversation_id, message_id)
            if bound:
                logger.info("attached %d file(s) to message %s", bound, message_id)
        except Exception:  # noqa: BLE001 - a missing card is not a failed turn
            logger.exception("could not attach documents to message %s", message_id)

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
            # Files uploaded since the last message belong to this one. Doing it
            # here, in the same transaction that persists the question, is what
            # makes the composer and the transcript agree after a reload.
            await self._attach_pending_documents(session, conversation.id, user_message.id)
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


async def _updates(tool: Tool, arguments: dict[str, Any]) -> AsyncIterator[ToolUpdate]:
    """A tool's output as a stream, whichever kind of tool it is.

    A tool that narrates yields as it goes; one that does not is adapted into a
    single batch, so the caller has one shape to handle and neither kind needs
    to know the other exists.
    """
    if isinstance(tool, ProgressiveTool):
        async for update in tool.stream(**arguments):
            yield update
        return
    yield Results(items=tuple(await tool.run(**arguments)))


def _facts(built: Built) -> str:
    """What it actually is and how it actually looks, for the model to use.

    It never sees the document. Told only that something was made, it
    described a warm orange-on-ink landing page as "a clean blue and white
    colour scheme", and a four-page site as "a single-page website" -- both
    confidently, both invented.
    """
    spec = built.spec
    said = []
    if built.summary:
        said.append(f"It is {built.summary}.")
    if spec.movement:
        look = f"Its look: {spec.movement}"
        said.append(f"{look} -- {spec.rationale}" if spec.rationale else f"{look}.")
    if spec.display_font and spec.body_font:
        said.append(f"Set in {spec.display_font} and {spec.body_font}.")
    if not said:
        return ""
    return (
        " " + " ".join(said)
        + " Describe it only from these facts; never name a colour or a layout "
        "you have not been told."
    )


def _caveats(note: str) -> str:
    """What did not go to plan, for the model to pass on.

    Without this it cheerfully reports a sunset photograph that is not there,
    because from where it sits the change succeeded.
    """
    if not note:
        return ""
    return f" Tell them this, plainly and in one sentence: {note}"


def _searches(tool: Tool) -> bool:
    """Decided by shape, never by name — the same rule as everything else."""
    return isinstance(tool, SearchingTool) and bool(tool.searches)


def _needs_open_artifact(tool: Tool) -> bool:
    """Decided by shape, never by name — the same rule as everything else."""
    return isinstance(tool, ArtifactAwareTool) and bool(tool.wants_open_artifact)


def _asked_for(bound: dict[str, Any]) -> str:
    """What the model chose to look up, for the chip under the answer."""
    said = ", ".join(str(value) for value in bound.values() if str(value).strip())
    return said if len(said) <= 120 else f"{said[:119]}\u2026"


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

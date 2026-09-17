"""The news strip.

Returns headlines for the new-chat screen. Always 200: when news is
unavailable the list is empty and the UI hides the strip. A decoration that can
return an error is a decoration that can look broken.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser, SessionDep, SettingsDep
from app.providers.registry import build_provider
from app.services.news_service import NewsService
from app.tools.news_mcp import NewsMcpConfig

router = APIRouter(prefix="/news", tags=["news"])


@router.get("")
async def headlines(
    session: SessionDep,
    settings: SettingsDep,
    user: CurrentUser,
) -> dict[str, object]:
    config = NewsMcpConfig(
        command=settings.mcp_news_command,
        args=tuple(settings.mcp_news_arg_list),
        tool=settings.mcp_news_tool,
        language=settings.mcp_news_language,
        country=settings.mcp_news_country,
        timeout=settings.mcp_news_timeout_seconds,
        max_items=settings.mcp_news_max_items,
    )
    items, from_cache, query = await NewsService(
        session, config, settings.mcp_news_ttl_seconds
    ).personalised(
        user_id=user.id,
        provider=build_provider(settings),
        max_per_user=settings.memory_max_per_user,
    )

    return {
        "items": [item.as_dict() for item in items],
        "cached": from_cache,
        # Empty when the general front page was used. The UI shows it so a
        # personalised strip does not look like a random selection.
        "topic": query,
    }

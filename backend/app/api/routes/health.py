"""Health and configuration probes.

`/api/health` is what Docker waits on. `/api/config` tells the frontend which
optional features are actually usable, so the UI can disable what is not
configured instead of offering a button that fails.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.artifacts.registry import build_kinds
from app.core.config import get_settings
from app.db.session import check_connection

router = APIRouter(tags=["health"])
settings = get_settings()


@router.get("/health")
async def health() -> JSONResponse:
    database_ok = await check_connection()
    payload = {
        "status": "ok" if database_ok else "degraded",
        "app": settings.app_name,
        "database": "ok" if database_ok else "unreachable",
    }
    return JSONResponse(status_code=200 if database_ok else 503, content=payload)


@router.get("/config")
async def public_config() -> dict[str, object]:
    """Non-secret configuration the browser is allowed to know.

    No key, URL or secret is ever included here — only whether a capability is
    available, so the UI can grey out what will not work.
    """
    return {
        "app_name": settings.app_name,
        "model": settings.llm_model,
        "search_enabled": settings.search_enabled,
        "images_enabled": settings.vision_enabled,
        "currency": settings.llm_price_currency,
        "supported_languages": settings.supported_language_list,
        # What can be made, straight from the registry, so a kind added there
        # appears in the composer without anybody editing a list.
        "makeable": [
            {"name": kind.name, "label": kind.label, "description": kind.description}
            for kind in build_kinds(settings).values()
        ],
    }

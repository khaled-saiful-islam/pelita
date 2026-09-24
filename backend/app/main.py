"""FastAPI application assembly.

This module wires HTTP to logic and does nothing else. Routers live in
`app/api/routes/`, and everything they call lives under `app/services/`.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import (
    admin,
    artifacts,
    auth,
    chat,
    conversations,
    documents,
    health,
    memories,
    news,
    shares,
)
from app.core.config import deployment_warnings, get_settings
from app.core.errors import PelitaError, RateLimitError
from app.core.logging import configure_logging

settings = get_settings()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(settings.log_level)
    logger.info(
        "%s starting — model=%s base_url=%s",
        settings.app_name,
        settings.llm_model,
        settings.llm_base_url,
    )
    _check_deployment_safety()

    yield

    # A turn now outlives the request that asked for it, so something has to
    # end it: otherwise a reload leaves the model being polled for an answer
    # nobody can receive, and the process will not exit until it finishes.
    from app.artifacts.raster import shutdown as close_renderer
    from app.db.session import engine
    from app.services.live_turns import live_turns

    await live_turns.close_all()
    # The renderer holds a browser process; a reload that left one behind would
    # leak one per restart.
    await close_renderer()
    await engine.dispose()


def _check_deployment_safety() -> None:
    """Refuse to start in production with development credentials.

    A warning is easy to miss in a log; a template that boots happily with its
    shipped JWT secret is how that secret ends up on the internet.
    """
    problems = deployment_warnings(settings)
    if not problems:
        return
    if settings.app_env.lower() in {"production", "prod"}:
        raise RuntimeError(
            "Refusing to start in production with development configuration:\n  - "
            + "\n  - ".join(problems)
        )
    for problem in problems:
        logger.warning("insecure for production: %s", problem)


def create_app() -> FastAPI:
    app = FastAPI(
        title=f"{settings.app_name} API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(PelitaError)
    async def handle_pelita_error(_: Request, exc: PelitaError) -> JSONResponse:
        # Retry-After is the only header any of these carry, and it is the
        # difference between a client backing off and a client hammering.
        headers = (
            {"Retry-After": str(exc.retry_after)}
            if isinstance(exc, RateLimitError)
            else None
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
            headers=headers,
        )

    app.include_router(health.router, prefix="/api")
    app.include_router(admin.router, prefix="/api")
    app.include_router(artifacts.router, prefix="/api")
    app.include_router(artifacts.by_conversation, prefix="/api")
    app.include_router(artifacts.public_router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    app.include_router(chat.router, prefix="/api")
    app.include_router(conversations.router, prefix="/api")
    app.include_router(documents.router, prefix="/api")
    app.include_router(memories.router, prefix="/api")
    app.include_router(news.router, prefix="/api")
    app.include_router(shares.owner_router, prefix="/api")
    app.include_router(shares.public_router, prefix="/api")
    return app


app = create_app()

from __future__ import annotations

import httpx
import pytest

from app.main import create_app


@pytest.fixture
def client() -> httpx.AsyncClient:
    app = create_app()
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def test_config_exposes_capabilities_without_a_database(client) -> None:
    async with client as c:
        response = await c.get("/api/config")
    assert response.status_code == 200

    body = response.json()
    assert body["app_name"]
    assert body["model"]
    assert isinstance(body["search_enabled"], bool)
    assert body["supported_languages"]


async def test_config_never_leaks_secrets(client) -> None:
    """The browser learns whether a capability works, never how it is configured."""
    async with client as c:
        body = (await c.get("/api/config")).json()

    keys = set(body)
    forbidden = {"llm_api_key", "serpapi_key", "jwt_secret", "database_url", "llm_base_url"}
    assert not (keys & forbidden)
    assert not any("key" in k.lower() or "secret" in k.lower() for k in keys)


async def test_health_reports_degraded_when_database_is_unreachable(client, monkeypatch) -> None:
    """Docker waits on this, so a down database must fail the check, not pass it."""
    monkeypatch.setattr("app.api.routes.health.check_connection", _false)

    async with client as c:
        response = await c.get("/api/health")

    assert response.status_code == 503
    assert response.json()["database"] == "unreachable"


async def test_health_reports_ok_when_database_answers(client, monkeypatch) -> None:
    monkeypatch.setattr("app.api.routes.health.check_connection", _true)

    async with client as c:
        response = await c.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "app": "Pelita", "database": "ok"}


async def _false() -> bool:
    return False


async def _true() -> bool:
    return True

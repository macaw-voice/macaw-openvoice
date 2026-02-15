"""Testes do health endpoint e app factory."""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx

import macaw
from macaw.server.app import create_app


async def test_create_app_returns_fastapi_instance() -> None:
    app = create_app()
    assert app is not None
    assert app.title == "Macaw OpenVoice"


async def test_health_endpoint_returns_ok_without_worker_manager() -> None:
    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == macaw.__version__


async def test_health_endpoint_includes_models_loaded_when_registry_present() -> None:
    registry = MagicMock()
    registry.list_models.return_value = [MagicMock(), MagicMock()]
    app = create_app(registry=registry)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["models_loaded"] == 2


async def test_health_returns_ok_when_all_workers_ready() -> None:
    worker_manager = MagicMock()
    worker_manager.worker_summary.return_value = {
        "total": 2,
        "ready": 2,
        "starting": 0,
        "crashed": 0,
    }
    app = create_app(worker_manager=worker_manager)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/health")

    body = response.json()
    assert body["status"] == "ok"
    assert body["workers_ready"] == 2
    assert body["workers_total"] == 2


async def test_health_returns_loading_when_workers_still_starting() -> None:
    worker_manager = MagicMock()
    worker_manager.worker_summary.return_value = {
        "total": 2,
        "ready": 1,
        "starting": 1,
        "crashed": 0,
    }
    app = create_app(worker_manager=worker_manager)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/health")

    body = response.json()
    assert body["status"] == "loading"
    assert body["workers_ready"] == 1
    assert body["workers_total"] == 2


async def test_health_returns_degraded_when_worker_crashed() -> None:
    worker_manager = MagicMock()
    worker_manager.worker_summary.return_value = {
        "total": 2,
        "ready": 1,
        "starting": 0,
        "crashed": 1,
    }
    app = create_app(worker_manager=worker_manager)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/health")

    body = response.json()
    assert body["status"] == "degraded"
    assert body["workers_ready"] == 1
    assert body["workers_total"] == 2


async def test_app_state_stores_registry_and_scheduler() -> None:
    app = create_app(registry=None, scheduler=None)
    assert app.state.registry is None
    assert app.state.scheduler is None

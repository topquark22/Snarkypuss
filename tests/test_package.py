"""Tests for package metadata and the minimal HTTP application."""

import asyncio

import httpx

from snarkyctl import __version__
from snarkyctl.main import app


def test_package_has_development_version() -> None:
    assert __version__ == "0.1.0.dev2"


def test_liveness_endpoint() -> None:
    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="https://test") as client:
            return await client.get("/api/health/live")

    response = asyncio.run(request())

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "snarkyctl-web",
        "version": __version__,
    }

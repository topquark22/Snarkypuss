"""Tests for package metadata and the minimal HTTP application."""

from fastapi.testclient import TestClient

from snarkyctl import __version__
from snarkyctl.main import app


def test_package_has_development_version() -> None:
    assert __version__ == "0.1.0.dev0"


def test_liveness_endpoint() -> None:
    response = TestClient(app).get("/api/health/live")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "snarkyctl-web",
        "version": __version__,
    }

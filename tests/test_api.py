"""Tests for the read-only HTTP API."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import bcrypt
import httpx
import pytest

from snarkyctl.control.client import ControlClientError
from snarkyctl.control.protocol import ControlResponse
from snarkyctl.main import WebRuntime, create_app
from snarkyctl.providers.base import GatewayMode, VpnState, VpnStatus

REQUEST_ID = UUID("0de2718e-98b1-43a0-879f-867d87b81a75")


def make_runtime(tmp_path: Path) -> WebRuntime:
    auth_file = tmp_path / "auth.htpasswd"
    password_hash = bcrypt.hashpw(b"secret", bcrypt.gensalt()).decode()
    auth_file.write_text(f"admin:{password_hash}\n", encoding="utf-8")
    return WebRuntime(
        auth_file=auth_file,
        control_socket=tmp_path / "control.sock",
        control_timeout_seconds=10,
    )


def get(app: object, *, auth: tuple[str, str] | None = None) -> httpx.Response:
    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
        async with httpx.AsyncClient(transport=transport, base_url="https://test") as client:
            return await client.get("/api/v1/status", auth=auth)

    return asyncio.run(request())


def test_status_requires_authentication(tmp_path: Path) -> None:
    response = get(create_app(make_runtime(tmp_path)))

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Basic realm="SnarkyCtl"'
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_invalid_credentials_are_rejected(tmp_path: Path) -> None:
    response = get(create_app(make_runtime(tmp_path)), auth=("admin", "wrong"))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_missing_auth_file_returns_service_error(tmp_path: Path) -> None:
    runtime = WebRuntime(
        auth_file=tmp_path / "missing",
        control_socket=tmp_path / "control.sock",
        control_timeout_seconds=10,
    )
    response = get(create_app(runtime), auth=("admin", "secret"))

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "AUTHENTICATION_UNAVAILABLE"


def test_missing_configuration_returns_service_error(tmp_path: Path) -> None:
    response = get(
        create_app(config_path=tmp_path / "missing.yaml"),
        auth=("admin", "secret"),
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "CONFIGURATION_ERROR"


def test_runtime_is_loaded_from_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = make_runtime(tmp_path)
    loaded = SimpleNamespace(
        settings=SimpleNamespace(
            web=SimpleNamespace(auth_file=runtime.auth_file),
            control=SimpleNamespace(
                socket_path=runtime.control_socket,
                operation_timeout_seconds=runtime.control_timeout_seconds,
            ),
        )
    )
    control_response = ControlResponse(
        request_id=REQUEST_ID,
        success=True,
        message="ok",
        vpn_status=VpnStatus(
            state=VpnState.CONNECTED,
            provider="nordvpn",
            gateway_mode=GatewayMode.VPN,
        ),
    )
    monkeypatch.setattr("snarkyctl.main.load_config", lambda _path: loaded)
    monkeypatch.setattr("snarkyctl.main.ControlClient.status", lambda _self: control_response)
    application = create_app(config_path=tmp_path / "snarkyctl.yaml")

    response = get(application, auth=("admin", "secret"))

    assert response.status_code == 200
    assert application.state.runtime.control_socket == runtime.control_socket


def test_direct_mode_warns_about_public_ip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    control_response = ControlResponse(
        request_id=REQUEST_ID,
        success=True,
        message="ok",
        vpn_status=VpnStatus(
            state=VpnState.DISCONNECTED,
            provider="nordvpn",
            gateway_mode=GatewayMode.DIRECT,
        ),
    )
    monkeypatch.setattr("snarkyctl.main.ControlClient.status", lambda _self: control_response)

    response = get(create_app(make_runtime(tmp_path)), auth=("admin", "secret"))

    assert response.status_code == 200
    assert response.json()["public_ip_exposed"] is True
    assert "real public IP" in response.json()["exposure_warning"]


def test_vpn_mode_is_not_exposed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    control_response = ControlResponse(
        request_id=REQUEST_ID,
        success=True,
        message="ok",
        vpn_status=VpnStatus(
            state=VpnState.CONNECTED,
            provider="nordvpn",
            gateway_mode=GatewayMode.VPN,
        ),
    )
    monkeypatch.setattr("snarkyctl.main.ControlClient.status", lambda _self: control_response)

    response = get(create_app(make_runtime(tmp_path)), auth=("admin", "secret"))

    assert response.status_code == 200
    assert response.json()["public_ip_exposed"] is False
    assert response.json()["exposure_warning"] is None


def test_daemon_failure_is_structured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(_self: object) -> ControlResponse:
        raise ControlClientError("DAEMON_UNAVAILABLE", "not running")

    monkeypatch.setattr("snarkyctl.main.ControlClient.status", fail)
    response = get(create_app(make_runtime(tmp_path)), auth=("admin", "secret"))

    assert response.status_code == 502
    assert response.json() == {
        "error": {"code": "DAEMON_UNAVAILABLE", "message": "not running"}
    }


@pytest.mark.parametrize(
    "control_response, expected_code",
    [
        (
            ControlResponse(
                request_id=REQUEST_ID,
                success=False,
                error_code="PROVIDER_ERROR",
                message="provider failed",
            ),
            "PROVIDER_ERROR",
        ),
        (
            ControlResponse(request_id=REQUEST_ID, success=True, message="missing status"),
            "INVALID_RESPONSE",
        ),
    ],
)
def test_invalid_daemon_results_are_structured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    control_response: ControlResponse,
    expected_code: str,
) -> None:
    monkeypatch.setattr("snarkyctl.main.ControlClient.status", lambda _self: control_response)

    response = get(create_app(make_runtime(tmp_path)), auth=("admin", "secret"))

    assert response.status_code == 502
    assert response.json()["error"]["code"] == expected_code


def test_unknown_mode_reports_indeterminate_exposure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    control_response = ControlResponse(
        request_id=REQUEST_ID,
        success=True,
        message="ok",
        vpn_status=VpnStatus(state=VpnState.UNKNOWN, provider="nordvpn"),
    )
    monkeypatch.setattr("snarkyctl.main.ControlClient.status", lambda _self: control_response)

    response = get(create_app(make_runtime(tmp_path)), auth=("admin", "secret"))

    assert response.status_code == 200
    assert response.json()["public_ip_exposed"] is None
    assert "cannot be determined" in response.json()["exposure_warning"]

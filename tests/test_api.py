"""Tests for the read-only HTTP API."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import bcrypt
import httpx
import pytest

from snarkyctl.control.client import ControlClientError
from snarkyctl.control.protocol import ControlResponse
from snarkyctl.main import WebRuntime, create_app
from snarkyctl.providers.base import (
    GatewayMode,
    ProviderCapabilities,
    VpnState,
    VpnStatus,
    VpnTargetCatalog,
    VpnTargetSummary,
)
from snarkyctl.status import (
    ComponentFailure,
    DnsStatus,
    GatewayStatus,
    PublicIpStatus,
    SystemStatus,
)
from snarkyctl.targets.models import (
    ProviderTargetSchema,
    SelectorKind,
    StoredTarget,
    TargetCatalogue,
)

REQUEST_ID = UUID("0de2718e-98b1-43a0-879f-867d87b81a75")


def status_response(vpn_status: VpnStatus) -> ControlResponse:
    return ControlResponse(
        request_id=REQUEST_ID,
        success=True,
        message="ok",
        gateway_status=GatewayStatus(
            checked_at=datetime.now(UTC),
            vpn_status=vpn_status,
            dns=None,
            system=None,
        ),
    )


def make_runtime(tmp_path: Path) -> WebRuntime:
    auth_file = tmp_path / "auth.htpasswd"
    password_hash = bcrypt.hashpw(b"secret", bcrypt.gensalt()).decode()
    auth_file.write_text(f"admin:{password_hash}\n", encoding="utf-8")
    return WebRuntime(
        auth_file=auth_file,
        control_socket=tmp_path / "control.sock",
        control_timeout_seconds=10,
    )


def get(
    app: object,
    *,
    path: str = "/api/v1/status",
    auth: tuple[str, str] | None = None,
) -> httpx.Response:
    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
        async with httpx.AsyncClient(transport=transport, base_url="https://test") as client:
            return await client.get(path, auth=auth)

    return asyncio.run(request())


def post(
    app: object,
    *,
    path: str,
    json: object,
    auth: tuple[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
        async with httpx.AsyncClient(transport=transport, base_url="https://test") as client:
            request_headers = {
                "Origin": "https://test",
                "Sec-Fetch-Site": "same-origin",
                "X-SnarkyCtl-Request": "1",
            }
            if headers is not None:
                request_headers = headers
            return await client.post(path, json=json, auth=auth, headers=request_headers)

    return asyncio.run(request())


def put(
    app: object,
    *,
    path: str,
    json_body: object,
    auth: tuple[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    request_headers = {
        "Origin": "https://test",
        "Sec-Fetch-Site": "same-origin",
        "X-SnarkyCtl-Request": "1",
        "Content-Type": "application/json",
    }
    if headers is not None:
        request_headers = headers
    return request(
        app,
        method="PUT",
        path=path,
        content=json.dumps(json_body).encode(),
        auth=auth,
        headers=request_headers,
    )


def request(
    app: object,
    *,
    method: str,
    path: str,
    content: bytes | None = None,
    auth: tuple[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
        async with httpx.AsyncClient(transport=transport, base_url="https://test") as client:
            return await client.request(
                method,
                path,
                content=content,
                auth=auth,
                headers=headers,
            )

    return asyncio.run(send())


def test_status_requires_authentication(tmp_path: Path) -> None:
    response = get(create_app(make_runtime(tmp_path)))

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Basic realm="SnarkyCtl"'
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_dashboard_requires_authentication(tmp_path: Path) -> None:
    response = get(create_app(make_runtime(tmp_path)), path="/")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Basic realm="SnarkyCtl"'


def test_dashboard_has_provider_neutral_controls_and_external_assets(
    tmp_path: Path,
) -> None:
    application = create_app(make_runtime(tmp_path))

    response = get(application, path="/", auth=("admin", "secret"))

    assert response.status_code == 200
    assert "SnarkyCtl Gateway" in response.text
    assert "VPN control" in response.text
    assert 'id="vpn-target"' in response.text
    assert 'id="vpn-connect"' in response.text
    assert "Connect / switch" in response.text
    assert 'class="danger-zone"' in response.text
    assert 'id="mode-protected"' in response.text
    assert 'id="mode-locked"' in response.text
    assert 'id="mode-direct"' in response.text
    assert 'class="target-manager"' in response.text
    assert 'id="target-editor-list"' in response.text
    assert 'id="target-save"' in response.text
    assert "EXPOSE VPS IP" in response.text
    assert "provider_target" not in response.text
    assert "<form" not in response.text
    assert 'src="/static/dashboard.js"' in response.text
    assert 'href="/static/dashboard.css"' in response.text
    assert "DNS" in response.text
    assert "VPS health" in response.text
    assert "<script>" not in response.text
    assert "<style>" not in response.text


@pytest.mark.parametrize(
    ("path", "content_type"),
    [
        ("/static/dashboard.css", "text/css"),
        ("/static/dashboard.js", "text/javascript"),
    ],
)
def test_dashboard_assets_are_packaged(
    tmp_path: Path, path: str, content_type: str
) -> None:
    response = get(create_app(make_runtime(tmp_path)), path=path)

    assert response.status_code == 200
    assert content_type in response.headers["content-type"]


def test_dashboard_script_uses_target_alias_api_only(tmp_path: Path) -> None:
    response = get(
        create_app(make_runtime(tmp_path)),
        path="/static/dashboard.js",
    )

    assert response.status_code == 200
    assert 'fetch("/api/v2/vpn/targets"' in response.text
    assert 'fetch("/api/v2/vpn/connect"' in response.text
    assert "JSON.stringify({ target })" in response.text
    assert '"X-SnarkyCtl-Request": "1"' in response.text
    assert '"/api/v2/mode/protected"' in response.text
    assert '"/api/v2/mode/locked"' in response.text
    assert '"/api/v2/mode/direct"' in response.text
    assert 'placeholder.textContent = "Select a target…"' in response.text
    assert "targetSelect.value = currentTarget" in response.text
    assert "capabilities?.target_selection" in response.text
    assert "capabilities?.leak_protection_configuration" in response.text
    assert "provider_target" not in response.text


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_interactive_api_documentation_is_disabled(tmp_path: Path, path: str) -> None:
    response = get(create_app(make_runtime(tmp_path)), path=path)

    assert response.status_code == 404


def test_security_headers_are_set_on_success_and_error(tmp_path: Path) -> None:
    application = create_app(make_runtime(tmp_path))

    for response in (
        get(application, path="/api/health/live"),
        get(application),
    ):
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["strict-transport-security"] == "max-age=31536000"
        assert response.headers["permissions-policy"] == (
            "camera=(), geolocation=(), microphone=()"
        )
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


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
    control_response = status_response(
        VpnStatus(
            state=VpnState.CONNECTED,
            provider="nordvpn",
            gateway_mode=GatewayMode.VPN,
        )
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
    control_response = status_response(
        VpnStatus(
            state=VpnState.DISCONNECTED,
            provider="nordvpn",
            gateway_mode=GatewayMode.DIRECT,
        )
    )
    monkeypatch.setattr("snarkyctl.main.ControlClient.status", lambda _self: control_response)

    response = get(create_app(make_runtime(tmp_path)), auth=("admin", "secret"))

    assert response.status_code == 200
    assert response.json()["public_ip_exposed"] is True
    assert "real public IP" in response.json()["exposure_warning"]


def test_vpn_mode_is_not_exposed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    control_response = status_response(
        VpnStatus(
            state=VpnState.CONNECTED,
            provider="nordvpn",
            gateway_mode=GatewayMode.VPN,
        )
    )
    monkeypatch.setattr("snarkyctl.main.ControlClient.status", lambda _self: control_response)

    response = get(create_app(make_runtime(tmp_path)), auth=("admin", "secret"))

    assert response.status_code == 200
    assert response.json()["public_ip_exposed"] is False
    assert response.json()["exposure_warning"] is None


def test_v2_status_returns_local_components_and_partial_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    control_response = ControlResponse(
        request_id=REQUEST_ID,
        success=True,
        message="ok",
        gateway_status=GatewayStatus(
            checked_at=datetime(2026, 7, 24, 15, 30, tzinfo=UTC),
            vpn_status=VpnStatus(
                state=VpnState.CONNECTED,
                provider="nordvpn",
                gateway_mode=GatewayMode.VPN,
            ),
            dns=DnsStatus(
                service="dnsmasq.service",
                load_state="loaded",
                active_state="active",
                sub_state="running",
            ),
            system=SystemStatus(
                uptime_seconds=120,
                load_average=(0.1, 0.2, 0.3),
                memory_total_bytes=2000,
                memory_available_bytes=1000,
                root_disk_total_bytes=4000,
                root_disk_free_bytes=3000,
            ),
            public_ip=PublicIpStatus(
                address="203.0.113.42",
                checked_at=datetime(2026, 7, 24, 15, 30, tzinfo=UTC),
            ),
            partial_failures=(
                ComponentFailure(
                    component="vpn_settings",
                    code="PROVIDER_TIMEOUT",
                    message="settings timed out",
                ),
            ),
        ),
    )
    monkeypatch.setattr("snarkyctl.main.ControlClient.status", lambda _self: control_response)

    response = get(
        create_app(make_runtime(tmp_path)),
        path="/api/v2/status",
        auth=("admin", "secret"),
    )

    assert response.status_code == 200
    assert response.json()["version"] == 2
    assert response.json()["dns"]["active_state"] == "active"
    assert response.json()["system"]["uptime_seconds"] == 120
    assert response.json()["public_ip"]["address"] == "203.0.113.42"
    assert response.json()["partial_failures"][0]["component"] == "vpn_settings"


def test_v2_status_survives_missing_vpn_component(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    control_response = ControlResponse(
        request_id=REQUEST_ID,
        success=True,
        message="partial",
        gateway_status=GatewayStatus(
            checked_at=datetime.now(UTC),
            vpn_status=None,
            dns=None,
            system=None,
            partial_failures=(
                ComponentFailure(
                    component="vpn",
                    code="PROVIDER_TIMEOUT",
                    message="provider timed out",
                ),
            ),
        ),
    )
    monkeypatch.setattr("snarkyctl.main.ControlClient.status", lambda _self: control_response)

    response = get(
        create_app(make_runtime(tmp_path)),
        path="/api/v2/status",
        auth=("admin", "secret"),
    )

    assert response.status_code == 200
    assert response.json()["vpn_status"] is None
    assert response.json()["public_ip_exposed"] is None


def test_target_catalogue_requires_authentication(tmp_path: Path) -> None:
    response = get(
        create_app(make_runtime(tmp_path)),
        path="/api/v2/vpn/targets",
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_target_catalogue_is_provider_neutral(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    control_response = ControlResponse(
        request_id=REQUEST_ID,
        success=True,
        message="ok",
        target_catalog=VpnTargetCatalog(
            provider="nordvpn",
            capabilities=ProviderCapabilities(
                connect=True,
                disconnect=True,
                target_selection=True,
                server_details=True,
                leak_protection_configuration=True,
            ),
            targets=(
                VpnTargetSummary(alias="dallas", label="Dallas, United States"),
                VpnTargetSummary(alias="prague", label="Prague, Czechia"),
            ),
        ),
    )
    monkeypatch.setattr("snarkyctl.main.ControlClient.targets", lambda _self: control_response)

    response = get(
        create_app(make_runtime(tmp_path)),
        path="/api/v2/vpn/targets",
        auth=("admin", "secret"),
    )

    assert response.status_code == 200
    assert response.json() == {
        "version": 2,
        "provider": "nordvpn",
        "capabilities": {
            "connect": True,
            "disconnect": True,
            "target_selection": True,
            "server_details": True,
            "leak_protection_configuration": True,
        },
        "targets": [
            {"alias": "dallas", "label": "Dallas, United States"},
            {"alias": "prague", "label": "Prague, Czechia"},
        ],
    }
    assert "provider_target" not in response.text


def _active_provider_response() -> ControlResponse:
    return ControlResponse(
        request_id=REQUEST_ID,
        success=True,
        message="ok",
        target_catalog=VpnTargetCatalog(
            provider="nordvpn",
            capabilities=ProviderCapabilities(
                connect=True,
                disconnect=True,
                target_selection=True,
                server_details=True,
            ),
            targets=(VpnTargetSummary(alias="dallas", label="Dallas"),),
        ),
    )


def test_admin_schema_and_catalogue_are_authenticated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    schema_response = ControlResponse(
        request_id=REQUEST_ID,
        success=True,
        message="ok",
        provider_target_schema=ProviderTargetSchema(
            provider="nordvpn",
            selector_kinds=(SelectorKind(kind="recommended", label="Recommended"),),
        ),
    )
    catalogue_response = ControlResponse(
        request_id=REQUEST_ID,
        success=True,
        message="ok",
        editable_target_catalogue=TargetCatalogue(
            provider="nordvpn",
            revision=3,
            targets=(
                StoredTarget(
                    alias="dallas",
                    label="Dallas",
                    position=0,
                    selector={"kind": "recommended"},
                ),
            ),
        ),
    )
    monkeypatch.setattr(
        "snarkyctl.main.ControlClient.targets",
        lambda _self: _active_provider_response(),
    )
    monkeypatch.setattr(
        "snarkyctl.main.ControlClient.target_schema",
        lambda _self, _provider: schema_response,
    )
    monkeypatch.setattr(
        "snarkyctl.main.ControlClient.editable_catalogue",
        lambda _self, _provider: catalogue_response,
    )
    app = create_app(make_runtime(tmp_path))
    assert get(app, path="/api/v3/admin/vpn/targets").status_code == 401
    schema = get(
        app,
        path="/api/v3/admin/vpn/target-schema",
        auth=("admin", "secret"),
    )
    catalogue = get(
        app,
        path="/api/v3/admin/vpn/targets",
        auth=("admin", "secret"),
    )
    assert schema.status_code == 200
    assert schema.json()["selector_kinds"][0]["kind"] == "recommended"
    assert catalogue.status_code == 200
    assert catalogue.json()["revision"] == 3
    assert catalogue.json()["targets"][0]["selector"] == {"kind": "recommended"}


def test_admin_catalogue_replace_requires_same_origin_and_maps_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conflict = ControlResponse(
        request_id=REQUEST_ID,
        success=False,
        error_code="CATALOG_CONFLICT",
        message="Catalogue revision is stale.",
    )
    monkeypatch.setattr(
        "snarkyctl.main.ControlClient.replace_catalogue",
        lambda *_args: conflict,
    )
    body = {
        "provider": "nordvpn",
        "expected_revision": 3,
        "targets": [
            {
                "alias": "dallas",
                "label": "Dallas",
                "position": 0,
                "selector": {"kind": "recommended"},
            }
        ],
    }
    app = create_app(make_runtime(tmp_path))
    forged = put(
        app,
        path="/api/v3/admin/vpn/targets",
        json_body=body,
        auth=("admin", "secret"),
        headers={"Content-Type": "application/json"},
    )
    response = put(
        app,
        path="/api/v3/admin/vpn/targets",
        json_body=body,
        auth=("admin", "secret"),
    )
    assert forged.status_code == 403
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CATALOG_CONFLICT"


def test_admin_catalogue_replace_returns_committed_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalogue = TargetCatalogue(
        provider="nordvpn",
        revision=4,
        targets=(
            StoredTarget(
                alias="canada",
                label="Canada",
                position=0,
                selector={"kind": "country", "country": "ca"},
            ),
        ),
    )
    monkeypatch.setattr(
        "snarkyctl.main.ControlClient.replace_catalogue",
        lambda *_args: ControlResponse(
            request_id=REQUEST_ID,
            success=True,
            message="ok",
            editable_target_catalogue=catalogue,
        ),
    )
    response = put(
        create_app(make_runtime(tmp_path)),
        path="/api/v3/admin/vpn/targets",
        auth=("admin", "secret"),
        json_body={
            "provider": "nordvpn",
            "expected_revision": 3,
            "targets": [catalogue.targets[0].model_dump(mode="json")],
        },
    )
    assert response.status_code == 200
    assert response.json()["revision"] == 4


@pytest.mark.parametrize(
    ("control_response", "expected_code"),
    [
        (
            ControlResponse(
                request_id=REQUEST_ID,
                success=False,
                error_code="CATALOGUE_ERROR",
                message="catalogue unavailable",
            ),
            "CATALOGUE_ERROR",
        ),
        (
            ControlResponse(request_id=REQUEST_ID, success=True, message="missing catalogue"),
            "INVALID_RESPONSE",
        ),
    ],
)
def test_invalid_target_catalogue_results_are_structured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    control_response: ControlResponse,
    expected_code: str,
) -> None:
    monkeypatch.setattr(
        "snarkyctl.main.ControlClient.targets",
        lambda _self: control_response,
    )

    response = get(
        create_app(make_runtime(tmp_path)),
        path="/api/v2/vpn/targets",
        auth=("admin", "secret"),
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == expected_code


def test_connect_requires_authentication(tmp_path: Path) -> None:
    response = post(
        create_app(make_runtime(tmp_path)),
        path="/api/v2/vpn/connect",
        json={"target": "dallas"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_connect_rejects_cors_preflight(tmp_path: Path) -> None:
    response = request(
        create_app(make_runtime(tmp_path)),
        method="OPTIONS",
        path="/api/v2/vpn/connect",
        headers={
            "Origin": "https://attacker.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-snarkyctl-request",
        },
    )

    assert response.status_code == 405
    assert "access-control-allow-origin" not in response.headers


def test_connect_rejects_non_json_content_before_daemon_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(_self: object, _target: str) -> ControlResponse:
        raise AssertionError("non-JSON request must not reach the control daemon")

    monkeypatch.setattr("snarkyctl.main.ControlClient.connect", forbidden)

    response = request(
        create_app(make_runtime(tmp_path)),
        method="POST",
        path="/api/v2/vpn/connect",
        content=b'{"target":"dallas"}',
        auth=("admin", "secret"),
        headers={
            "Content-Type": "text/plain",
            "Origin": "https://test",
            "Sec-Fetch-Site": "same-origin",
            "X-SnarkyCtl-Request": "1",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Origin": "https://test", "Sec-Fetch-Site": "same-origin"},
        {
            "Origin": "https://attacker.example",
            "Sec-Fetch-Site": "cross-site",
            "X-SnarkyCtl-Request": "1",
        },
        {
            "Origin": "https://attacker.example",
            "Sec-Fetch-Site": "same-origin",
            "X-SnarkyCtl-Request": "1",
        },
    ],
)
def test_connect_rejects_cross_origin_requests_before_daemon_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    headers: dict[str, str],
) -> None:
    def forbidden(_self: object, _target: str) -> ControlResponse:
        raise AssertionError("cross-origin request must not reach the control daemon")

    monkeypatch.setattr("snarkyctl.main.ControlClient.connect", forbidden)

    response = post(
        create_app(make_runtime(tmp_path)),
        path="/api/v2/vpn/connect",
        json={"target": "dallas"},
        auth=("admin", "secret"),
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CROSS_ORIGIN_REQUEST"


def test_connect_allows_non_browser_client_with_request_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "snarkyctl.main.ControlClient.connect",
        lambda _self, target: ControlResponse(
            request_id=REQUEST_ID,
            success=True,
            message=f"Connected using target alias {target}.",
            vpn_status=VpnStatus(
                state=VpnState.CONNECTED,
                provider="fake",
                gateway_mode=GatewayMode.VPN,
                target=target,
            ),
        ),
    )

    response = post(
        create_app(make_runtime(tmp_path)),
        path="/api/v2/vpn/connect",
        json={"target": "dallas"},
        auth=("admin", "secret"),
        headers={"X-SnarkyCtl-Request": "1"},
    )

    assert response.status_code == 200


def test_connect_passes_only_target_alias_to_control_daemon(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    received: list[str] = []

    def connect(_self: object, target: str) -> ControlResponse:
        received.append(target)
        return ControlResponse(
            request_id=REQUEST_ID,
            success=True,
            message="Connected using target alias dallas.",
            vpn_status=VpnStatus(
                state=VpnState.CONNECTED,
                provider="nordvpn",
                gateway_mode=GatewayMode.VPN,
                target="dallas",
                display_name="United States #6275",
                interface="nordlynx",
            ),
        )

    monkeypatch.setattr("snarkyctl.main.ControlClient.connect", connect)

    response = post(
        create_app(make_runtime(tmp_path)),
        path="/api/v2/vpn/connect",
        json={"target": "dallas"},
        auth=("admin", "secret"),
    )

    assert response.status_code == 200
    assert received == ["dallas"]
    assert response.json()["version"] == 2
    assert response.json()["vpn_status"]["target"] == "dallas"
    assert response.json()["vpn_status"]["provider"] == "nordvpn"
    assert response.json()["public_ip_exposed"] is False
    assert "provider_target" not in response.text


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"target": "Dallas, United States"},
        {"target": "../../bin/sh"},
        {"target": "dallas", "command": "id"},
    ],
)
def test_connect_rejects_malformed_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    body: dict[str, object],
) -> None:
    def forbidden(_self: object, _target: str) -> ControlResponse:
        raise AssertionError("invalid request must not reach the control daemon")

    monkeypatch.setattr("snarkyctl.main.ControlClient.connect", forbidden)

    response = post(
        create_app(make_runtime(tmp_path)),
        path="/api/v2/vpn/connect",
        json=body,
        auth=("admin", "secret"),
    )

    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "code": "INVALID_REQUEST",
            "message": "request body does not match the API schema",
        }
    }


@pytest.mark.parametrize(
    ("control_response", "expected_status", "expected_code"),
    [
        (
            ControlResponse(
                request_id=REQUEST_ID,
                success=False,
                error_code="UNKNOWN_TARGET",
                message="The requested target alias is not configured.",
            ),
            404,
            "UNKNOWN_TARGET",
        ),
        (
            ControlResponse(
                request_id=REQUEST_ID,
                success=False,
                error_code="OPERATION_IN_PROGRESS",
                message="Another VPN control operation is already in progress.",
            ),
            409,
            "OPERATION_IN_PROGRESS",
        ),
        (
            ControlResponse(
                request_id=REQUEST_ID,
                success=False,
                error_code="PROVIDER_TIMEOUT",
                message="Provider timed out.",
            ),
            504,
            "PROVIDER_TIMEOUT",
        ),
        (
            ControlResponse(
                request_id=REQUEST_ID,
                success=False,
                error_code="PROVIDER_COMMAND_FAILED",
                message="Provider command failed.",
            ),
            502,
            "PROVIDER_COMMAND_FAILED",
        ),
        (
            ControlResponse(request_id=REQUEST_ID, success=True, message="missing status"),
            502,
            "INVALID_RESPONSE",
        ),
    ],
)
def test_connect_daemon_results_are_structured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    control_response: ControlResponse,
    expected_status: int,
    expected_code: str,
) -> None:
    monkeypatch.setattr(
        "snarkyctl.main.ControlClient.connect",
        lambda _self, _target: control_response,
    )

    response = post(
        create_app(make_runtime(tmp_path)),
        path="/api/v2/vpn/connect",
        json={"target": "dallas"},
        auth=("admin", "secret"),
    )

    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == expected_code


def test_connect_transport_timeout_returns_gateway_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def timeout(_self: object, _target: str) -> ControlResponse:
        raise ControlClientError("DAEMON_TIMEOUT", "control daemon did not respond in time")

    monkeypatch.setattr("snarkyctl.main.ControlClient.connect", timeout)

    response = post(
        create_app(make_runtime(tmp_path)),
        path="/api/v2/vpn/connect",
        json={"target": "dallas"},
        auth=("admin", "secret"),
    )

    assert response.status_code == 504
    assert response.json()["error"]["code"] == "DAEMON_TIMEOUT"


@pytest.mark.parametrize(
    ("path", "method", "body", "mode", "exposed"),
    [
        (
            "/api/v2/mode/protected",
            "protected",
            {"target": "dallas"},
            GatewayMode.VPN,
            False,
        ),
        (
            "/api/v2/mode/locked",
            "lock",
            {},
            GatewayMode.LOCKED,
            False,
        ),
        (
            "/api/v2/mode/direct",
            "direct",
            {"confirmation": "EXPOSE VPS IP"},
            GatewayMode.DIRECT,
            True,
        ),
    ],
)
def test_gateway_mode_endpoints_return_exposure_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    method: str,
    body: dict[str, str],
    mode: GatewayMode,
    exposed: bool,
) -> None:
    received: list[tuple[object, ...]] = []

    def operation(_self: object, *arguments: object) -> ControlResponse:
        received.append(arguments)
        return ControlResponse(
            request_id=REQUEST_ID,
            success=True,
            message=f"{mode.value} enabled.",
            vpn_status=VpnStatus(
                state=(
                    VpnState.CONNECTED
                    if mode is GatewayMode.VPN
                    else VpnState.DISCONNECTED
                ),
                provider="fake",
                gateway_mode=mode,
                leak_protection_active=mode is not GatewayMode.DIRECT,
                target="dallas" if mode is GatewayMode.VPN else None,
            ),
        )

    monkeypatch.setattr(f"snarkyctl.main.ControlClient.{method}", operation)

    response = post(
        create_app(make_runtime(tmp_path)),
        path=path,
        json=body,
        auth=("admin", "secret"),
    )

    assert response.status_code == 200
    assert response.json()["vpn_status"]["gateway_mode"] == mode.value
    assert response.json()["public_ip_exposed"] is exposed
    assert received


def test_direct_mode_requires_exact_confirmation_before_daemon_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(_self: object, _confirmation: str) -> ControlResponse:
        raise AssertionError("invalid confirmation must not reach the daemon")

    monkeypatch.setattr("snarkyctl.main.ControlClient.direct", forbidden)

    response = post(
        create_app(make_runtime(tmp_path)),
        path="/api/v2/mode/direct",
        json={"confirmation": "yes"},
        auth=("admin", "secret"),
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_mode_endpoint_requires_same_origin_marker(tmp_path: Path) -> None:
    response = post(
        create_app(make_runtime(tmp_path)),
        path="/api/v2/mode/locked",
        json={},
        auth=("admin", "secret"),
        headers={},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CROSS_ORIGIN_REQUEST"


def test_bodyless_mode_endpoint_still_requires_json_content_type(
    tmp_path: Path,
) -> None:
    response = request(
        create_app(make_runtime(tmp_path)),
        method="POST",
        path="/api/v2/mode/locked",
        auth=("admin", "secret"),
        headers={
            "Origin": "https://test",
            "Sec-Fetch-Site": "same-origin",
            "X-SnarkyCtl-Request": "1",
        },
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "INVALID_CONTENT_TYPE"


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
    control_response = status_response(
        VpnStatus(state=VpnState.UNKNOWN, provider="nordvpn")
    )
    monkeypatch.setattr("snarkyctl.main.ControlClient.status", lambda _self: control_response)

    response = get(create_app(make_runtime(tmp_path)), auth=("admin", "secret"))

    assert response.status_code == 200
    assert response.json()["public_ip_exposed"] is None
    assert "cannot be determined" in response.json()["exposure_warning"]

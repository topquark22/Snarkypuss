"""Tests for safe control-daemon startup and request handling."""

import os
import pwd
import socket
from types import SimpleNamespace
from uuid import UUID

import pytest

from snarkyctl.control import daemon
from snarkyctl.control.daemon import ActivationError
from snarkyctl.control.protocol import (
    ConnectRequest,
    ControlResponse,
    DisconnectRequest,
    LockRequest,
    Operation,
    StatusRequest,
    encode_message,
    receive_frame,
)
from snarkyctl.providers.base import (
    GatewayMode,
    ProviderCapabilities,
    ProviderError,
    VpnProvider,
    VpnSettings,
    VpnState,
    VpnStatus,
    VpnTarget,
)

REQUEST_ID = UUID("0de2718e-98b1-43a0-879f-867d87b81a75")


class FakeProvider(VpnProvider):
    name = "fake"
    capabilities = ProviderCapabilities(
        connect=True, disconnect=True, target_selection=True, server_details=True
    )

    def __init__(self) -> None:
        self.connected_target: VpnTarget | None = None

    def status(self) -> VpnStatus:
        state = VpnState.CONNECTED if self.connected_target else VpnState.DISCONNECTED
        return VpnStatus(state=state, provider="fake")

    def settings(self) -> VpnSettings:
        return VpnSettings(
            provider="fake",
            leak_protection_enabled=True,
            firewall_enabled=True,
        )

    def connect(self, target: VpnTarget) -> VpnStatus:
        self.connected_target = target
        return VpnStatus(state=VpnState.CONNECTED, provider="fake", target=target.alias)

    def disconnect(self) -> VpnStatus:
        self.connected_target = None
        return VpnStatus(state=VpnState.DISCONNECTED, provider="fake")


def control_service(provider: VpnProvider | None = None) -> daemon.ControlService:
    configured_target = VpnTarget(
        alias="dallas", label="Dallas, United States", provider_target="us9167"
    )
    config = SimpleNamespace(targets=SimpleNamespace(targets=(configured_target,)))
    return daemon.ControlService(config, provider or FakeProvider())  # type: ignore[arg-type]


def test_daemon_refuses_non_socket_activated_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LISTEN_PID", raising=False)
    monkeypatch.delenv("LISTEN_FDS", raising=False)

    with pytest.raises(ActivationError, match="variables are missing"):
        daemon.systemd_listener()


def test_daemon_rejects_wrong_activation_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LISTEN_PID", str(os.getpid() + 1))
    monkeypatch.setenv("LISTEN_FDS", "1")

    with pytest.raises(ActivationError, match="does not identify"):
        daemon.systemd_listener()


def test_daemon_requires_exactly_one_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LISTEN_PID", str(os.getpid()))
    monkeypatch.setenv("LISTEN_FDS", "2")

    with pytest.raises(ActivationError, match="exactly one"):
        daemon.systemd_listener()


def test_daemon_accepts_one_activated_unix_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    listener, peer = socket.socketpair()
    inherited_fd = os.dup(listener.fileno())
    monkeypatch.setenv("LISTEN_PID", str(os.getpid()))
    monkeypatch.setenv("LISTEN_FDS", "1")
    monkeypatch.setattr(daemon, "SYSTEMD_FIRST_SOCKET_FD", inherited_fd)

    try:
        activated = daemon.systemd_listener()
        assert activated.family == socket.AF_UNIX
        assert activated.type & socket.SOCK_STREAM
        activated.close()
    finally:
        listener.close()
        peer.close()


def test_allowed_uids_include_root_and_service_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pwd,
        "getpwnam",
        lambda _name: SimpleNamespace(pw_uid=1234),
    )

    assert daemon.allowed_uids() == frozenset({0, 1234})


def test_missing_service_account_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing_user(_name: str) -> None:
        raise KeyError

    monkeypatch.setattr(pwd, "getpwnam", missing_user)

    with pytest.raises(ActivationError, match="does not exist"):
        daemon.allowed_uids()


def test_peer_credentials_report_current_process() -> None:
    server, client = socket.socketpair()
    try:
        pid, uid, gid = daemon.peer_credentials(server)
    finally:
        server.close()
        client.close()

    assert pid == os.getpid()
    assert uid == os.getuid()
    assert gid == os.getgid()


def test_valid_status_request_is_dispatched() -> None:
    server, client = socket.socketpair()
    request = StatusRequest(version=1, request_id=REQUEST_ID, operation=Operation.STATUS)
    try:
        client.sendall(encode_message(request))
        daemon.handle_connection(server, frozenset({os.getuid()}), control_service())
        response = ControlResponse.model_validate_json(receive_frame(client))
    finally:
        server.close()
        client.close()

    assert response.request_id == REQUEST_ID
    assert response.success is True
    assert response.vpn_status is not None
    assert response.vpn_status.state is VpnState.DISCONNECTED
    assert response.vpn_status.gateway_mode is GatewayMode.LOCKED


def test_control_service_connects_only_configured_alias() -> None:
    provider = FakeProvider()
    service = control_service(provider)
    request = ConnectRequest(
        version=1, request_id=REQUEST_ID, operation=Operation.CONNECT, target="dallas"
    )
    response = service.dispatch(request)
    assert response.success
    assert provider.connected_target is not None
    assert provider.connected_target.provider_target == "us9167"


def test_control_service_rejects_unknown_alias_without_provider_call() -> None:
    provider = FakeProvider()
    service = control_service(provider)
    request = ConnectRequest(
        version=1, request_id=REQUEST_ID, operation=Operation.CONNECT, target="unknown"
    )
    response = service.dispatch(request)
    assert not response.success
    assert response.error_code == "UNKNOWN_TARGET"
    assert provider.connected_target is None


def test_control_service_disconnects_provider() -> None:
    provider = FakeProvider()
    provider.connected_target = VpnTarget(
        alias="dallas", label="Dallas", provider_target="us9167"
    )
    request = DisconnectRequest(
        version=1, request_id=REQUEST_ID, operation=Operation.DISCONNECT
    )
    response = control_service(provider).dispatch(request)
    assert response.success
    assert response.vpn_status is not None
    assert response.vpn_status.state is VpnState.DISCONNECTED
    assert response.vpn_status.gateway_mode is GatewayMode.LOCKED


def test_control_service_refuses_unsafe_disconnect() -> None:
    class UnsafeProvider(FakeProvider):
        def settings(self) -> VpnSettings:
            return VpnSettings(
                provider="fake",
                leak_protection_enabled=False,
                firewall_enabled=True,
            )

        def disconnect(self) -> VpnStatus:
            raise AssertionError("disconnect must not be called")

    request = DisconnectRequest(
        version=1, request_id=REQUEST_ID, operation=Operation.DISCONNECT
    )
    response = control_service(UnsafeProvider()).dispatch(request)
    assert not response.success
    assert response.error_code == "UNSAFE_DISCONNECT"


def test_policy_operations_remain_unavailable() -> None:
    request = LockRequest(version=1, request_id=REQUEST_ID, operation=Operation.LOCK)
    response = control_service().dispatch(request)
    assert not response.success
    assert response.error_code == "NOT_IMPLEMENTED"


def test_unauthorized_peer_is_rejected() -> None:
    server, client = socket.socketpair()
    try:
        daemon.handle_connection(server, frozenset(), control_service())
    finally:
        server.close()
        client.close()


def test_invalid_request_is_rejected_without_response() -> None:
    server, client = socket.socketpair()
    try:
        client.sendall(b"\x00\x00\x00\x03bad")
        daemon.handle_connection(server, frozenset({os.getuid()}), control_service())
    finally:
        server.close()
        client.close()


def test_provider_error_is_returned_as_controlled_response() -> None:
    class FailingProvider(FakeProvider):
        def status(self) -> VpnStatus:
            raise ProviderError("PROVIDER_TIMEOUT", "NordVPN command timed out")

    server, client = socket.socketpair()
    request = StatusRequest(version=1, request_id=REQUEST_ID, operation=Operation.STATUS)
    try:
        client.sendall(encode_message(request))
        daemon.handle_connection(
            server, frozenset({os.getuid()}), control_service(FailingProvider())
        )
        response = ControlResponse.model_validate_json(receive_frame(client))
    finally:
        server.close()
        client.close()
    assert not response.success
    assert response.error_code == "PROVIDER_TIMEOUT"

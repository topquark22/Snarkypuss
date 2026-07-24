"""Tests for safe control-daemon startup and request handling."""

import os
import pwd
import socket
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from uuid import UUID

import pytest

from snarkyctl.control import daemon
from snarkyctl.control.daemon import ActivationError
from snarkyctl.control.protocol import (
    ConnectRequest,
    ControlResponse,
    DirectRequest,
    DisconnectRequest,
    LockRequest,
    Operation,
    PROTOCOL_VERSION,
    ProtectedRequest,
    StatusRequest,
    TargetCatalogGetRequest,
    TargetCatalogReplaceRequest,
    TargetSchemaRequest,
    TargetsRequest,
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
from snarkyctl.status import PublicIpStatus, StatusCollectionError
from snarkyctl.targets.models import (
    ProviderTargetSchema,
    SelectorKind,
    StoredTarget,
    TargetCatalogue,
)
from snarkyctl.targets.repository import (
    MemoryTargetRepository,
    RepositoryError,
    TargetRepository,
)

REQUEST_ID = UUID("0de2718e-98b1-43a0-879f-867d87b81a75")


class FakeProvider(VpnProvider):
    name = "fake"
    capabilities = ProviderCapabilities(
        connect=True,
        disconnect=True,
        target_selection=True,
        server_details=True,
        leak_protection_configuration=True,
    )

    def __init__(self) -> None:
        self.connected_target: VpnTarget | None = None
        self.protection_enabled = True

    def status(self) -> VpnStatus:
        state = VpnState.CONNECTED if self.connected_target else VpnState.DISCONNECTED
        return VpnStatus(state=state, provider="fake")

    def settings(self) -> VpnSettings:
        return VpnSettings(
            provider="fake",
            leak_protection_enabled=self.protection_enabled,
            firewall_enabled=True,
        )

    def connect(self, target: VpnTarget) -> VpnStatus:
        self.connected_target = target
        return VpnStatus(state=VpnState.CONNECTED, provider="fake")

    def target_schema(self) -> ProviderTargetSchema:
        return ProviderTargetSchema(
            provider="fake",
            selector_kinds=(SelectorKind(kind="legacy", label="Legacy"),),
        )

    def disconnect(self) -> VpnStatus:
        self.connected_target = None
        return VpnStatus(state=VpnState.DISCONNECTED, provider="fake")

    def set_leak_protection(self, enabled: bool) -> VpnSettings:
        self.protection_enabled = enabled
        return self.settings()


def control_service(
    provider: VpnProvider | None = None,
    *,
    public_ip_collector: object | None = None,
    target_repository: TargetRepository | None = None,
) -> daemon.ControlService:
    configured_target = VpnTarget(
        alias="dallas", label="Dallas, United States", provider_target="us9167"
    )
    config = SimpleNamespace(
        settings=SimpleNamespace(
            status=SimpleNamespace(
                public_ip_url="https://api.ipify.org",
                public_ip_timeout_seconds=5,
            )
        ),
        targets=SimpleNamespace(targets=(configured_target,)),
    )
    collector = public_ip_collector or (
        lambda _url, _timeout: PublicIpStatus(
            address="203.0.113.42",
            checked_at=datetime.now(UTC),
        )
    )
    return daemon.ControlService(  # type: ignore[arg-type]
        config,
        provider or FakeProvider(),
        local_collector=lambda: (None, None, []),
        public_ip_collector=collector,
        target_repository=target_repository,
    )


def test_control_service_from_config_selects_sqlite_only_when_explicit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    database = tmp_path / "targets.db"
    repository = MemoryTargetRepository()
    config = SimpleNamespace(
        settings=SimpleNamespace(
            upstream_vpn=SimpleNamespace(
                provider="fake",
                targets=SimpleNamespace(path=database),
            ),
            control=SimpleNamespace(operation_timeout_seconds=60),
            status=SimpleNamespace(
                public_ip_url="https://api.ipify.org",
                public_ip_timeout_seconds=5,
            ),
        ),
        targets=None,
    )
    checked: list[Path] = []
    monkeypatch.setattr(daemon, "load_config", lambda _path: config)
    monkeypatch.setattr(daemon, "create_provider", lambda *_args, **_kwargs: FakeProvider())
    monkeypatch.setattr(daemon, "check_database", checked.append)
    monkeypatch.setattr(daemon, "SqliteTargetRepository", lambda _path: repository)
    service = daemon.ControlService.from_config(tmp_path / "snarkyctl.yaml")
    assert checked == [database]
    assert service._target_repository is repository


def test_control_service_requires_yaml_when_no_repository_is_supplied() -> None:
    config = SimpleNamespace(
        settings=SimpleNamespace(
            status=SimpleNamespace(
                public_ip_url="https://api.ipify.org",
                public_ip_timeout_seconds=5,
            )
        ),
        targets=None,
    )
    with pytest.raises(daemon.ConfigError, match="YAML target"):
        daemon.ControlService(config, FakeProvider())  # type: ignore[arg-type]


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
    request = StatusRequest(
        version=PROTOCOL_VERSION, request_id=REQUEST_ID, operation=Operation.STATUS
    )
    try:
        client.sendall(encode_message(request))
        daemon.handle_connection(server, frozenset({os.getuid()}), control_service())
        response = ControlResponse.model_validate_json(receive_frame(client))
    finally:
        server.close()
        client.close()

    assert response.request_id == REQUEST_ID
    assert response.success is True
    assert response.gateway_status is not None
    assert response.gateway_status.vpn_status is not None
    assert response.gateway_status.vpn_status.state is VpnState.DISCONNECTED
    assert response.gateway_status.vpn_status.gateway_mode is GatewayMode.LOCKED
    assert response.gateway_status.public_ip is None


def test_connected_status_includes_public_exit_ip() -> None:
    provider = FakeProvider()
    provider.connected_target = VpnTarget(
        alias="dallas", label="Dallas", provider_target="us9167"
    )
    request = StatusRequest(
        version=PROTOCOL_VERSION, request_id=REQUEST_ID, operation=Operation.STATUS
    )

    response = control_service(provider).dispatch(request)

    assert response.gateway_status is not None
    assert response.gateway_status.public_ip is not None
    assert str(response.gateway_status.public_ip.address) == "203.0.113.42"


def test_daemon_resolves_connection_alias_through_repository() -> None:
    provider = FakeProvider()
    repository = MemoryTargetRepository(
        (
            TargetCatalogue(
                provider="fake",
                revision=3,
                targets=(
                    StoredTarget(
                        alias="prague",
                        label="Prague",
                        position=0,
                        selector={"kind": "legacy", "value": "cz"},
                    ),
                ),
            ),
        )
    )
    service = control_service(provider, target_repository=repository)
    response = service.dispatch(
        ConnectRequest(
            version=PROTOCOL_VERSION,
            request_id=REQUEST_ID,
            operation=Operation.CONNECT,
            target="prague",
        )
    )
    assert response.success
    assert provider.connected_target is not None
    assert provider.connected_target.provider_target == "cz"


def test_daemon_returns_schema_and_editable_catalogue() -> None:
    service = control_service()
    schema = service.dispatch(
        TargetSchemaRequest(
            version=PROTOCOL_VERSION,
            request_id=REQUEST_ID,
            operation=Operation.TARGET_SCHEMA,
            provider="fake",
        )
    )
    catalogue = service.dispatch(
        TargetCatalogGetRequest(
            version=PROTOCOL_VERSION,
            request_id=REQUEST_ID,
            operation=Operation.TARGET_CATALOG_GET,
            provider="fake",
        )
    )
    assert schema.success
    assert schema.provider_target_schema is not None
    assert catalogue.success
    assert catalogue.editable_target_catalogue is not None
    assert catalogue.editable_target_catalogue.targets[0].selector["value"] == "us9167"


def test_daemon_commits_replacement_before_switching_snapshot() -> None:
    repository = MemoryTargetRepository(
        (
            TargetCatalogue(
                provider="fake",
                revision=2,
                targets=(
                    StoredTarget(
                        alias="old",
                        label="Old",
                        position=0,
                        selector={"kind": "legacy", "value": "old"},
                    ),
                ),
            ),
        )
    )
    service = control_service(target_repository=repository)
    replacement = service.dispatch(
        TargetCatalogReplaceRequest(
            version=PROTOCOL_VERSION,
            request_id=REQUEST_ID,
            operation=Operation.TARGET_CATALOG_REPLACE,
            provider="fake",
            expected_revision=2,
            targets=(
                StoredTarget(
                    alias="new",
                    label="New",
                    position=0,
                    selector={"kind": "legacy", "value": "new"},
                ),
            ),
        )
    )
    assert replacement.success
    assert replacement.editable_target_catalogue is not None
    assert replacement.editable_target_catalogue.revision == 3
    connected = service.dispatch(
        ConnectRequest(
            version=PROTOCOL_VERSION,
            request_id=REQUEST_ID,
            operation=Operation.CONNECT,
            target="new",
        )
    )
    assert connected.success


def test_daemon_preserves_snapshot_after_repository_failure() -> None:
    class FailingRepository(MemoryTargetRepository):
        def replace_catalogue(
            self,
            provider: str,
            expected_revision: int,
            targets: tuple[StoredTarget, ...],
        ) -> TargetCatalogue:
            raise RepositoryError("CATALOG_STORAGE_FAILED", "disk failure")

    initial = TargetCatalogue(
        provider="fake",
        revision=1,
        targets=(
            StoredTarget(
                alias="old",
                label="Old",
                position=0,
                selector={"kind": "legacy", "value": "old"},
            ),
        ),
    )
    service = control_service(target_repository=FailingRepository((initial,)))
    response = service.dispatch(
        TargetCatalogReplaceRequest(
            version=PROTOCOL_VERSION,
            request_id=REQUEST_ID,
            operation=Operation.TARGET_CATALOG_REPLACE,
            provider="fake",
            expected_revision=1,
            targets=(
                StoredTarget(
                    alias="new",
                    label="New",
                    position=0,
                    selector={"kind": "legacy", "value": "new"},
                ),
            ),
        )
    )
    assert not response.success
    assert response.error_code == "CATALOG_STORAGE_FAILED"
    assert service.dispatch(
        ConnectRequest(
            version=PROTOCOL_VERSION,
            request_id=REQUEST_ID,
            operation=Operation.CONNECT,
            target="old",
        )
    ).success


def test_daemon_rejects_unknown_provider_and_yaml_replacement() -> None:
    service = control_service()
    unknown = service.dispatch(
        TargetCatalogGetRequest(
            version=PROTOCOL_VERSION,
            request_id=REQUEST_ID,
            operation=Operation.TARGET_CATALOG_GET,
            provider="other",
        )
    )
    read_only = service.dispatch(
        TargetCatalogReplaceRequest(
            version=PROTOCOL_VERSION,
            request_id=REQUEST_ID,
            operation=Operation.TARGET_CATALOG_REPLACE,
            provider="fake",
            expected_revision=0,
            targets=(
                StoredTarget(
                    alias="new",
                    label="New",
                    position=0,
                    selector={"kind": "legacy", "value": "new"},
                ),
            ),
        )
    )
    assert unknown.error_code == "UNKNOWN_PROVIDER"
    assert read_only.error_code == "CATALOG_MIGRATION_REQUIRED"


def test_daemon_rejects_empty_or_adapter_invalid_catalogue() -> None:
    repository = MemoryTargetRepository()
    service = control_service(target_repository=repository)
    empty = service.dispatch(
        TargetCatalogReplaceRequest(
            version=PROTOCOL_VERSION,
            request_id=REQUEST_ID,
            operation=Operation.TARGET_CATALOG_REPLACE,
            provider="fake",
            expected_revision=0,
            targets=(),
        )
    )
    invalid = service.dispatch(
        TargetCatalogReplaceRequest(
            version=PROTOCOL_VERSION,
            request_id=REQUEST_ID,
            operation=Operation.TARGET_CATALOG_REPLACE,
            provider="fake",
            expected_revision=0,
            targets=(
                StoredTarget(
                    alias="bad",
                    label="Bad",
                    position=0,
                    selector={"kind": "recommended"},
                ),
            ),
        )
    )
    assert empty.error_code == "INVALID_CATALOG"
    assert invalid.error_code == "INVALID_CATALOG"
    assert repository.get_catalogue("fake").revision == 0


def test_daemon_rejects_target_administration_for_unsupported_provider() -> None:
    provider = FakeProvider()
    provider.capabilities = ProviderCapabilities(
        connect=True,
        disconnect=True,
        target_selection=False,
        server_details=False,
    )
    service = control_service(provider, target_repository=MemoryTargetRepository())
    schema = service.dispatch(
        TargetSchemaRequest(
            version=PROTOCOL_VERSION,
            request_id=REQUEST_ID,
            operation=Operation.TARGET_SCHEMA,
            provider="fake",
        )
    )
    replacement = service.dispatch(
        TargetCatalogReplaceRequest(
            version=PROTOCOL_VERSION,
            request_id=REQUEST_ID,
            operation=Operation.TARGET_CATALOG_REPLACE,
            provider="fake",
            expected_revision=0,
            targets=(
                StoredTarget(
                    alias="new",
                    label="New",
                    position=0,
                    selector={"kind": "legacy", "value": "new"},
                ),
            ),
        )
    )
    assert schema.error_code == "UNSUPPORTED_TARGET_SELECTION"
    assert replacement.error_code == "UNSUPPORTED_TARGET_SELECTION"


def test_locked_status_does_not_make_external_request() -> None:
    def forbidden(_url: str, _timeout: float) -> PublicIpStatus:
        raise AssertionError("public-IP lookup must not run in Locked mode")

    request = StatusRequest(
        version=PROTOCOL_VERSION, request_id=REQUEST_ID, operation=Operation.STATUS
    )

    response = control_service(public_ip_collector=forbidden).dispatch(request)

    assert response.success
    assert response.gateway_status is not None
    assert response.gateway_status.public_ip is None


def test_public_ip_failure_is_partial() -> None:
    provider = FakeProvider()
    provider.connected_target = VpnTarget(
        alias="dallas", label="Dallas", provider_target="us9167"
    )

    def fail(_url: str, _timeout: float) -> PublicIpStatus:
        raise StatusCollectionError(
            "PUBLIC_IP_TLS_FAILED",
            "public-IP service certificate verification failed",
        )

    request = StatusRequest(
        version=PROTOCOL_VERSION, request_id=REQUEST_ID, operation=Operation.STATUS
    )
    response = control_service(provider, public_ip_collector=fail).dispatch(request)

    assert response.success
    assert response.gateway_status is not None
    assert response.gateway_status.public_ip is None
    assert response.gateway_status.partial_failures[0].component == "public_ip"


def test_control_service_connects_only_configured_alias() -> None:
    provider = FakeProvider()
    service = control_service(provider)
    request = ConnectRequest(
        version=PROTOCOL_VERSION,
        request_id=REQUEST_ID,
        operation=Operation.CONNECT,
        target="dallas",
    )
    response = service.dispatch(request)
    assert response.success
    assert provider.connected_target is not None
    assert provider.connected_target.provider_target == "us9167"
    assert response.vpn_status is not None
    assert response.vpn_status.target == "dallas"

    status_response = service.dispatch(
        StatusRequest(
            version=PROTOCOL_VERSION,
            request_id=UUID("f2299d89-5bbd-4db4-aa83-f23753fb532d"),
            operation=Operation.STATUS,
        )
    )
    assert status_response.gateway_status is not None
    assert status_response.gateway_status.vpn_status is not None
    assert status_response.gateway_status.vpn_status.target == "dallas"


def test_control_service_rejects_competing_mutation_but_allows_status() -> None:
    entered = Event()
    release = Event()

    class BlockingProvider(FakeProvider):
        def connect(self, target: VpnTarget) -> VpnStatus:
            entered.set()
            assert release.wait(timeout=2)
            return super().connect(target)

    provider = BlockingProvider()
    service = control_service(provider)
    connect_request = ConnectRequest(
        version=PROTOCOL_VERSION,
        request_id=REQUEST_ID,
        operation=Operation.CONNECT,
        target="dallas",
    )
    disconnect_request = DisconnectRequest(
        version=PROTOCOL_VERSION,
        request_id=UUID("e67d7ea1-34b4-481d-a16d-f2d33031af68"),
        operation=Operation.DISCONNECT,
    )
    status_request = StatusRequest(
        version=PROTOCOL_VERSION,
        request_id=UUID("5976f162-3a2b-473e-8ffc-c8d65cad4d40"),
        operation=Operation.STATUS,
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(service.dispatch, connect_request)
        assert entered.wait(timeout=2)

        competing = service.dispatch(disconnect_request)
        status = service.dispatch(status_request)
        targets = service.dispatch(
            TargetsRequest(
                version=PROTOCOL_VERSION,
                request_id=UUID("adcc4b91-7676-48d9-a68c-d519f05f1351"),
                operation=Operation.TARGETS,
            )
        )
        release.set()
        completed = first.result(timeout=2)
        followup = service.dispatch(disconnect_request)

    assert not competing.success
    assert competing.error_code == "OPERATION_IN_PROGRESS"
    assert status.success
    assert status.gateway_status is not None
    assert targets.success
    assert targets.target_catalog is not None
    assert completed.success
    assert followup.success


def test_control_service_releases_operation_lock_after_provider_failure() -> None:
    class FailOnceProvider(FakeProvider):
        def __init__(self) -> None:
            super().__init__()
            self.fail = True

        def connect(self, target: VpnTarget) -> VpnStatus:
            if self.fail:
                self.fail = False
                raise ProviderError("PROVIDER_COMMAND_FAILED", "first call failed")
            return super().connect(target)

    request = ConnectRequest(
        version=PROTOCOL_VERSION,
        request_id=REQUEST_ID,
        operation=Operation.CONNECT,
        target="dallas",
    )
    service = control_service(FailOnceProvider())

    with pytest.raises(ProviderError):
        service.dispatch(request)
    response = service.dispatch(request)

    assert response.success


def test_control_service_returns_sanitized_target_catalogue() -> None:
    request = TargetsRequest(
        version=PROTOCOL_VERSION,
        request_id=REQUEST_ID,
        operation=Operation.TARGETS,
    )

    response = control_service().dispatch(request)

    assert response.success
    assert response.target_catalog is not None
    assert response.target_catalog.provider == "fake"
    assert response.target_catalog.capabilities.target_selection
    assert response.target_catalog.targets[0].alias == "dallas"
    assert response.target_catalog.targets[0].label == "Dallas, United States"
    assert "provider_target" not in response.target_catalog.model_dump_json()
    assert "us9167" not in response.target_catalog.model_dump_json()


def test_control_service_rejects_unknown_alias_without_provider_call() -> None:
    provider = FakeProvider()
    service = control_service(provider)
    request = ConnectRequest(
        version=PROTOCOL_VERSION,
        request_id=REQUEST_ID,
        operation=Operation.CONNECT,
        target="unknown",
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
        version=PROTOCOL_VERSION, request_id=REQUEST_ID, operation=Operation.DISCONNECT
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
        version=PROTOCOL_VERSION, request_id=REQUEST_ID, operation=Operation.DISCONNECT
    )
    response = control_service(UnsafeProvider()).dispatch(request)
    assert not response.success
    assert response.error_code == "UNSAFE_DISCONNECT"


def test_protected_mode_enables_protection_before_connecting() -> None:
    calls: list[str] = []

    class RecordingProvider(FakeProvider):
        def set_leak_protection(self, enabled: bool) -> VpnSettings:
            calls.append(f"protection:{enabled}")
            return super().set_leak_protection(enabled)

        def connect(self, target: VpnTarget) -> VpnStatus:
            calls.append("connect")
            return super().connect(target)

    request = ProtectedRequest(
        version=PROTOCOL_VERSION,
        request_id=REQUEST_ID,
        operation=Operation.PROTECTED,
        target="dallas",
    )
    response = control_service(RecordingProvider()).dispatch(request)

    assert response.success
    assert calls == ["protection:True", "connect"]
    assert response.vpn_status is not None
    assert response.vpn_status.gateway_mode is GatewayMode.VPN


def test_locked_mode_enables_protection_before_disconnecting() -> None:
    calls: list[str] = []

    class RecordingProvider(FakeProvider):
        def set_leak_protection(self, enabled: bool) -> VpnSettings:
            calls.append(f"protection:{enabled}")
            return super().set_leak_protection(enabled)

        def disconnect(self) -> VpnStatus:
            calls.append("disconnect")
            return super().disconnect()

    request = LockRequest(
        version=PROTOCOL_VERSION, request_id=REQUEST_ID, operation=Operation.LOCK
    )
    response = control_service(RecordingProvider()).dispatch(request)

    assert response.success
    assert calls == ["protection:True", "disconnect"]
    assert response.vpn_status is not None
    assert response.vpn_status.gateway_mode is GatewayMode.LOCKED


def test_direct_mode_disables_protection_before_disconnecting() -> None:
    calls: list[str] = []

    class RecordingProvider(FakeProvider):
        def set_leak_protection(self, enabled: bool) -> VpnSettings:
            calls.append(f"protection:{enabled}")
            return super().set_leak_protection(enabled)

        def disconnect(self) -> VpnStatus:
            calls.append("disconnect")
            return super().disconnect()

    request = DirectRequest(
        version=PROTOCOL_VERSION,
        request_id=REQUEST_ID,
        operation=Operation.DIRECT,
        confirmation_token="EXPOSE VPS IP",
    )
    response = control_service(RecordingProvider()).dispatch(request)

    assert response.success
    assert calls == ["protection:False", "disconnect"]
    assert response.vpn_status is not None
    assert response.vpn_status.gateway_mode is GatewayMode.DIRECT


def test_direct_mode_restores_protection_when_disconnect_fails() -> None:
    class FailingProvider(FakeProvider):
        def disconnect(self) -> VpnStatus:
            raise ProviderError("PROVIDER_COMMAND_FAILED", "disconnect failed")

    provider = FailingProvider()
    request = DirectRequest(
        version=PROTOCOL_VERSION,
        request_id=REQUEST_ID,
        operation=Operation.DIRECT,
        confirmation_token="EXPOSE VPS IP",
    )

    with pytest.raises(ProviderError, match="disconnect failed"):
        control_service(provider).dispatch(request)

    assert provider.protection_enabled


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
    request = StatusRequest(
        version=PROTOCOL_VERSION, request_id=REQUEST_ID, operation=Operation.STATUS
    )
    try:
        client.sendall(encode_message(request))
        daemon.handle_connection(
            server, frozenset({os.getuid()}), control_service(FailingProvider())
        )
        response = ControlResponse.model_validate_json(receive_frame(client))
    finally:
        server.close()
        client.close()
    assert response.success
    assert response.gateway_status is not None
    assert response.gateway_status.vpn_status is None
    assert response.gateway_status.partial_failures[0].code == "PROVIDER_TIMEOUT"

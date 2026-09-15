"""Socket-activated privileged SnarkyCtl control daemon."""

from __future__ import annotations

import logging
import os
import pwd
import socket
import struct
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from threading import Lock

from snarkyctl.config import DEFAULT_CONFIG_PATH, ConfigError, LoadedConfig, load_config
from snarkyctl.control.protocol import (
    ConnectRequest,
    ControlRequest,
    ControlResponse,
    DirectRequest,
    DisconnectRequest,
    LockRequest,
    ProtocolError,
    ProtectedRequest,
    StatusRequest,
    TargetCatalogGetRequest,
    TargetCatalogReplaceRequest,
    TargetSchemaRequest,
    TargetsRequest,
    encode_message,
    parse_request,
    receive_frame,
)
from snarkyctl.providers.base import (
    GatewayMode,
    ProviderError,
    VpnProvider,
    VpnSettings,
    VpnState,
    VpnStatus,
    VpnTargetCatalog,
    VpnTargetSummary,
)
from snarkyctl.providers.registry import create_provider
from snarkyctl.status import (
    ComponentFailure,
    DnsStatus,
    PublicIpStatus,
    StatusCollectionError,
    SystemStatus,
    collect_local_status,
    collect_public_ip,
    new_gateway_status,
)
from snarkyctl.targets.lifecycle import check_database
from snarkyctl.targets.models import StoredTarget
from snarkyctl.targets.repository import RepositoryError, TargetRepository, YamlTargetRepository
from snarkyctl.targets.sqlite import SqliteTargetRepository

LOGGER = logging.getLogger("snarkyctl.control")
SYSTEMD_FIRST_SOCKET_FD = 3
CONTROL_IO_TIMEOUT_SECONDS = 5.0
CONTROL_WORKER_COUNT = 8
_PEER_CREDENTIALS = struct.Struct("3i")


class ActivationError(RuntimeError):
    """Raised when the daemon was not started with one systemd socket."""


class ControlService:
    """Dispatch fixed protocol operations to one configured provider."""

    def __init__(
        self,
        config: LoadedConfig,
        provider: VpnProvider,
        local_collector: Callable[
            [], tuple[DnsStatus | None, SystemStatus | None, list[ComponentFailure]]
        ] | None = None,
        public_ip_collector: Callable[[str, float], PublicIpStatus] = collect_public_ip,
        target_repository: TargetRepository | None = None,
    ) -> None:
        self._provider = provider
        dns_address = str(config.settings.network.management_address.ip)
        self._local_collector = (
            local_collector
            if local_collector is not None
            else lambda: collect_local_status(dns_address=dns_address)
        )
        self._public_ip_collector = public_ip_collector
        self._public_ip_url = config.settings.status.public_ip_url
        self._public_ip_timeout_seconds = config.settings.status.public_ip_timeout_seconds
        self._operation_lock = Lock()
        self._current_target_alias: str | None = None
        repository = target_repository
        if repository is None:
            if config.targets is None:
                raise ConfigError("YAML target configuration is unavailable")
            repository = YamlTargetRepository(
                provider.name,
                config.targets.targets,
                provider.import_legacy_target,
            )
        self._target_repository = repository
        self._catalogue = repository.get_catalogue(provider.name)
        self._targets = {target.alias: target for target in self._catalogue.targets}

    @classmethod
    def from_config(cls, path: Path = DEFAULT_CONFIG_PATH) -> ControlService:
        """Load root-owned configuration and construct its compiled provider."""
        config = load_config(path)
        provider = create_provider(
            config.settings.upstream_vpn.provider,
            timeout_seconds=config.settings.control.operation_timeout_seconds,
        )
        storage = config.settings.upstream_vpn.targets
        repository: TargetRepository | None = None
        if storage is not None:
            check_database(storage.path)
            repository = SqliteTargetRepository(storage.path)
        return cls(config, provider, target_repository=repository)

    def dispatch(self, request: ControlRequest) -> ControlResponse:
        """Execute one already validated request."""
        if not isinstance(
            request,
            (
                ConnectRequest,
                DisconnectRequest,
                ProtectedRequest,
                LockRequest,
                DirectRequest,
                TargetCatalogReplaceRequest,
            ),
        ):
            return self._dispatch_unlocked(request)
        if not self._operation_lock.acquire(blocking=False):
            return ControlResponse(
                request_id=request.request_id,
                success=False,
                error_code="OPERATION_IN_PROGRESS",
                message="Another VPN control operation is already in progress.",
            )
        try:
            return self._dispatch_unlocked(request)
        finally:
            self._operation_lock.release()

    def _dispatch_unlocked(self, request: ControlRequest) -> ControlResponse:
        """Execute a request after any required operation lock is acquired."""
        if isinstance(request, TargetSchemaRequest):
            if response := self._require_active_provider(request):
                return response
            if not self._provider.capabilities.target_selection:
                return ControlResponse(
                    request_id=request.request_id,
                    success=False,
                    error_code="UNSUPPORTED_TARGET_SELECTION",
                    message=f"{self._provider.name} does not support target selection.",
                )
            return ControlResponse(
                request_id=request.request_id,
                success=True,
                message="Provider target schema retrieved.",
                provider_target_schema=self._provider.target_schema(),
            )
        if isinstance(request, TargetCatalogGetRequest):
            if response := self._require_active_provider(request):
                return response
            return ControlResponse(
                request_id=request.request_id,
                success=True,
                message="Editable target catalogue retrieved.",
                editable_target_catalogue=self._catalogue,
            )
        if isinstance(request, TargetCatalogReplaceRequest):
            if response := self._require_active_provider(request):
                return response
            if not self._provider.capabilities.target_selection:
                return ControlResponse(
                    request_id=request.request_id,
                    success=False,
                    error_code="UNSUPPORTED_TARGET_SELECTION",
                    message=f"{self._provider.name} does not support target selection.",
                )
            if not request.targets:
                return ControlResponse(
                    request_id=request.request_id,
                    success=False,
                    error_code="INVALID_CATALOG",
                    message="A target catalogue must contain at least one target.",
                )
            try:
                normalized = tuple(
                    StoredTarget(
                        alias=target.alias,
                        label=target.label,
                        position=target.position,
                        selector=self._provider.validate_selector(target.selector),
                    )
                    for target in request.targets
                )
                catalogue = self._target_repository.replace_catalogue(
                    request.provider,
                    request.expected_revision,
                    normalized,
                )
            except ProviderError as exc:
                return ControlResponse(
                    request_id=request.request_id,
                    success=False,
                    error_code="INVALID_CATALOG",
                    message=str(exc),
                )
            except RepositoryError as exc:
                code = (
                    "CATALOG_MIGRATION_REQUIRED"
                    if exc.code == "READ_ONLY_REPOSITORY"
                    else exc.code
                )
                return ControlResponse(
                    request_id=request.request_id,
                    success=False,
                    error_code=code,
                    message=str(exc),
                )
            self._catalogue = catalogue
            self._targets = {target.alias: target for target in catalogue.targets}
            return ControlResponse(
                request_id=request.request_id,
                success=True,
                message="Target catalogue replaced.",
                editable_target_catalogue=catalogue,
            )
        if isinstance(request, TargetsRequest):
            catalog = VpnTargetCatalog(
                provider=self._provider.name,
                capabilities=self._provider.capabilities,
                targets=tuple(
                    VpnTargetSummary(alias=target.alias, label=target.label)
                    for target in self._targets.values()
                ),
            )
            return ControlResponse(
                request_id=request.request_id,
                success=True,
                message="Configured VPN targets retrieved.",
                target_catalog=catalog,
            )
        if isinstance(request, StatusRequest):
            failures: list[ComponentFailure] = []
            status: VpnStatus | None
            try:
                status = self._provider.status()
            except ProviderError as exc:
                status = None
                failures.append(
                    ComponentFailure(component="vpn", code=exc.code, message=str(exc))
                )
            if status is not None:
                if (
                    self._current_target_alias is not None
                    and status.state in {VpnState.CONNECTED, VpnState.CONNECTING}
                ):
                    status = status.model_copy(
                        update={"target": self._current_target_alias}
                    )
                elif status.state is VpnState.DISCONNECTED:
                    self._current_target_alias = None
                try:
                    settings = self._provider.settings()
                except ProviderError as exc:
                    settings = None
                    failures.append(
                        ComponentFailure(
                            component="vpn_settings",
                            code=exc.code,
                            message=str(exc),
                        )
                    )
                status = self._with_gateway_mode(status, settings)
            public_ip: PublicIpStatus | None = None
            if status is not None and status.gateway_mode in {
                GatewayMode.VPN,
                GatewayMode.DIRECT,
            }:
                try:
                    public_ip = self._public_ip_collector(
                        self._public_ip_url,
                        self._public_ip_timeout_seconds,
                    )
                except StatusCollectionError as exc:
                    failures.append(
                        ComponentFailure(
                            component="public_ip",
                            code=exc.code,
                            message=str(exc),
                        )
                    )
            dns, system, local_failures = self._local_collector()
            failures.extend(local_failures)
            return ControlResponse(
                request_id=request.request_id,
                success=True,
                message="Gateway status retrieved.",
                gateway_status=new_gateway_status(
                    vpn_status=status,
                    public_ip=public_ip,
                    dns=dns,
                    system=system,
                    partial_failures=failures,
                ),
            )
        if isinstance(request, ProtectedRequest):
            try:
                target = self._targets[request.target]
            except KeyError:
                return ControlResponse(
                    request_id=request.request_id,
                    success=False,
                    error_code="UNKNOWN_TARGET",
                    message="The requested target alias is not configured.",
                )
            self._require_protection_configuration()
            settings = self._provider.set_leak_protection(True)
            if settings.leak_protection_enabled is not True:
                raise ProviderError(
                    "PROTECTION_NOT_ENABLED",
                    "Provider did not confirm that leak protection is enabled.",
                )
            status = self._provider.connect_stored(target)
            status = status.model_copy(update={"target": target.alias})
            self._current_target_alias = target.alias
            status = self._with_gateway_mode(status, self._provider.settings())
            if status.gateway_mode is not GatewayMode.VPN:
                raise ProviderError(
                    "MODE_TRANSITION_FAILED",
                    "Provider did not reach protected VPN mode.",
                )
            return ControlResponse(
                request_id=request.request_id,
                success=True,
                message=f"Protected VPN mode enabled using target alias {target.alias}.",
                vpn_status=status,
            )
        if isinstance(request, ConnectRequest):
            try:
                target = self._targets[request.target]
            except KeyError:
                return ControlResponse(
                    request_id=request.request_id,
                    success=False,
                    error_code="UNKNOWN_TARGET",
                    message="The requested target alias is not configured.",
                )
            status = self._provider.connect_stored(target)
            status = status.model_copy(update={"target": target.alias})
            self._current_target_alias = target.alias
            try:
                settings = self._provider.settings()
            except ProviderError:
                settings = None
            status = self._with_gateway_mode(status, settings)
            return ControlResponse(
                request_id=request.request_id,
                success=True,
                message=f"Connected using target alias {target.alias}.",
                vpn_status=status,
            )
        if isinstance(request, DisconnectRequest):
            settings = self._provider.settings()
            if not (
                settings.leak_protection_enabled is True
                and settings.firewall_enabled is True
            ):
                return ControlResponse(
                    request_id=request.request_id,
                    success=False,
                    error_code="UNSAFE_DISCONNECT",
                    message=(
                        "Disconnect refused because provider leak protection "
                        "and firewall are not verified enabled."
                    ),
                )
            status = self._provider.disconnect()
            self._current_target_alias = None
            status = self._with_gateway_mode(status, settings)
            return ControlResponse(
                request_id=request.request_id,
                success=True,
                message="Upstream VPN disconnected.",
                vpn_status=status,
            )
        if isinstance(request, LockRequest):
            self._require_protection_configuration()
            settings = self._provider.set_leak_protection(True)
            if settings.leak_protection_enabled is not True:
                raise ProviderError(
                    "PROTECTION_NOT_ENABLED",
                    "Provider did not confirm that leak protection is enabled.",
                )
            status = self._provider.disconnect()
            self._current_target_alias = None
            status = self._with_gateway_mode(status, self._provider.settings())
            if status.gateway_mode is not GatewayMode.LOCKED:
                raise ProviderError(
                    "MODE_TRANSITION_FAILED",
                    "Provider did not reach Locked mode.",
                )
            return ControlResponse(
                request_id=request.request_id,
                success=True,
                message="Locked mode enabled; public forwarding is protected.",
                vpn_status=status,
            )
        if isinstance(request, DirectRequest):
            self._require_protection_configuration()
            try:
                settings = self._provider.set_leak_protection(False)
                if settings.leak_protection_enabled is not False:
                    raise ProviderError(
                        "PROTECTION_NOT_DISABLED",
                        "Provider did not confirm that leak protection is disabled.",
                    )
                status = self._provider.disconnect()
                self._current_target_alias = None
                status = self._with_gateway_mode(status, self._provider.settings())
                if status.gateway_mode is not GatewayMode.DIRECT:
                    raise ProviderError(
                        "MODE_TRANSITION_FAILED",
                        "Provider did not reach Direct VPS mode.",
                    )
            except ProviderError:
                self._restore_leak_protection()
                raise
            return ControlResponse(
                request_id=request.request_id,
                success=True,
                message="Direct VPS mode enabled; the VPS public IP is exposed.",
                vpn_status=status,
            )
        raise AssertionError("unreachable validated control request")

    def _require_active_provider(
        self,
        request: TargetSchemaRequest | TargetCatalogGetRequest | TargetCatalogReplaceRequest,
    ) -> ControlResponse | None:
        if request.provider == self._provider.name:
            return None
        return ControlResponse(
           
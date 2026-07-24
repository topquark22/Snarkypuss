"""Socket-activated privileged SnarkyCtl control daemon."""

from __future__ import annotations

import logging
import os
import pwd
import socket
import struct
from collections.abc import Callable
from contextlib import closing
from pathlib import Path

from snarkyctl.config import DEFAULT_CONFIG_PATH, ConfigError, LoadedConfig, load_config
from snarkyctl.control.protocol import (
    ConnectRequest,
    ControlRequest,
    ControlResponse,
    DirectRequest,
    DisconnectRequest,
    LockRequest,
    ProtocolError,
    StatusRequest,
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
    VpnTarget,
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

LOGGER = logging.getLogger("snarkyctl.control")
SYSTEMD_FIRST_SOCKET_FD = 3
CONTROL_IO_TIMEOUT_SECONDS = 5.0
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
        ] = collect_local_status,
        public_ip_collector: Callable[[str, float], PublicIpStatus] = collect_public_ip,
    ) -> None:
        self._provider = provider
        self._local_collector = local_collector
        self._public_ip_collector = public_ip_collector
        self._public_ip_url = config.settings.status.public_ip_url
        self._public_ip_timeout_seconds = config.settings.status.public_ip_timeout_seconds
        self._targets: dict[str, VpnTarget] = {
            target.alias: target for target in config.targets.targets
        }

    @classmethod
    def from_config(cls, path: Path = DEFAULT_CONFIG_PATH) -> ControlService:
        """Load root-owned configuration and construct its compiled provider."""
        config = load_config(path)
        provider = create_provider(
            config.settings.upstream_vpn.provider,
            timeout_seconds=config.settings.control.operation_timeout_seconds,
        )
        return cls(config, provider)

    def dispatch(self, request: ControlRequest) -> ControlResponse:
        """Execute one already validated request."""
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
            status = self._provider.connect(target)
            status = status.model_copy(update={"target": target.alias})
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
            status = self._with_gateway_mode(status, settings)
            return ControlResponse(
                request_id=request.request_id,
                success=True,
                message="Upstream VPN disconnected.",
                vpn_status=status,
            )
        if isinstance(request, (LockRequest, DirectRequest)):
            return ControlResponse(
                request_id=request.request_id,
                success=False,
                error_code="NOT_IMPLEMENTED",
                message="This policy operation is not implemented yet.",
            )
        raise AssertionError("unreachable validated control request")

    @staticmethod
    def _with_gateway_mode(
        status: VpnStatus, settings: VpnSettings | None
    ) -> VpnStatus:
        protection = settings.leak_protection_enabled if settings is not None else None
        if status.state is VpnState.CONNECTED:
            mode = GatewayMode.VPN
        elif status.state is VpnState.DISCONNECTED and protection is True:
            mode = GatewayMode.LOCKED
        elif status.state is VpnState.DISCONNECTED and protection is False:
            mode = GatewayMode.DIRECT
        else:
            mode = GatewayMode.UNKNOWN
        return status.model_copy(
            update={"gateway_mode": mode, "leak_protection_active": protection}
        )


def systemd_listener() -> socket.socket:
    """Return the single Unix listener inherited from systemd."""
    try:
        listen_pid = int(os.environ["LISTEN_PID"])
        listen_fds = int(os.environ["LISTEN_FDS"])
    except (KeyError, ValueError) as exc:
        raise ActivationError("systemd socket activation variables are missing") from exc

    if listen_pid != os.getpid():
        raise ActivationError("LISTEN_PID does not identify this process")
    if listen_fds != 1:
        raise ActivationError("exactly one systemd listening socket is required")

    listener = socket.socket(fileno=SYSTEMD_FIRST_SOCKET_FD)
    if listener.family != socket.AF_UNIX or listener.type & socket.SOCK_STREAM == 0:
        listener.detach()
        raise ActivationError("the inherited descriptor is not a Unix stream socket")
    return listener


def allowed_uids() -> frozenset[int]:
    """Return UIDs allowed to request privileged control operations."""
    try:
        service_uid = pwd.getpwnam("snarkyctl").pw_uid
    except KeyError as exc:
        raise ActivationError("the snarkyctl service account does not exist") from exc
    return frozenset({0, service_uid})


def peer_credentials(connection: socket.socket) -> tuple[int, int, int]:
    """Return the Linux PID, UID, and GID for a connected Unix peer."""
    raw = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, _PEER_CREDENTIALS.size)
    return _PEER_CREDENTIALS.unpack(raw)


def _provider_failure(request: ControlRequest, error: ProviderError) -> ControlResponse:
    return ControlResponse(
        request_id=request.request_id,
        success=False,
        error_code=error.code,
        message=str(error),
    )


def handle_connection(
    connection: socket.socket,
    permitted_uids: frozenset[int],
    service: ControlService,
) -> None:
    """Authenticate, validate, dispatch, and respond to one local request."""
    connection.settimeout(CONTROL_IO_TIMEOUT_SECONDS)
    pid, uid, _gid = peer_credentials(connection)
    if uid not in permitted_uids:
        LOGGER.warning("rejected unauthorized control peer pid=%d uid=%d", pid, uid)
        return

    try:
        request = parse_request(receive_frame(connection))
        LOGGER.info(
            "control operation requested pid=%d uid=%d operation=%s",
            pid,
            uid,
            request.operation,
        )
        try:
            response = service.dispatch(request)
        except ProviderError as exc:
            LOGGER.warning(
                "provider operation failed pid=%d uid=%d operation=%s code=%s",
                pid,
                uid,
                request.operation,
                exc.code,
            )
            response = _provider_failure(request, exc)
        except Exception:
            LOGGER.exception(
                "unexpected provider failure pid=%d uid=%d operation=%s",
                pid,
                uid,
                request.operation,
            )
            response = ControlResponse(
                request_id=request.request_id,
                success=False,
                error_code="INTERNAL_ERROR",
                message="The control operation failed unexpectedly.",
            )
        connection.sendall(encode_message(response))
    except (OSError, ProtocolError) as exc:
        LOGGER.warning("rejected invalid control request pid=%d uid=%d: %s", pid, uid, exc)


def serve(listener: socket.socket, service: ControlService) -> None:  # pragma: no cover
    """Serve local requests serially until systemd stops the process."""
    permitted_uids = allowed_uids()
    LOGGER.info("SnarkyCtl control daemon ready")
    while True:
        connection, _address = listener.accept()
        with closing(connection):
            handle_connection(connection, permitted_uids, service)


def main() -> int:  # pragma: no cover - exercised by systemd integration tests
    """Load configuration and run the socket-activated control daemon."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        service = ControlService.from_config()
    except (ConfigError, ProviderError) as exc:
        LOGGER.error("control daemon configuration failed: %s", exc)
        return 1
    with closing(systemd_listener()) as listener:
        serve(listener, service)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

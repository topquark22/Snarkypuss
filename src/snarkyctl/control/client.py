"""Unprivileged client for the root control daemon."""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Literal
from uuid import uuid4

from snarkyctl.control.protocol import (
    PROTOCOL_VERSION,
    ConnectRequest,
    ControlRequest,
    ControlResponse,
    DisconnectRequest,
    DirectRequest,
    LockRequest,
    Operation,
    ProtocolError,
    ProtectedRequest,
    StatusRequest,
    TargetCatalogGetRequest,
    TargetCatalogReplaceRequest,
    TargetSchemaRequest,
    TargetsRequest,
    encode_message,
    parse_response,
    receive_frame,
)
from snarkyctl.targets.models import StoredTarget

DEFAULT_CONTROL_SOCKET = Path("/run/snarkyctl/control.sock")
DEFAULT_CONTROL_TIMEOUT_SECONDS = 65.0


class ControlClientError(RuntimeError):
    """Controlled failure while communicating with the control daemon."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ControlClient:
    """Send validated requests to the privileged daemon over its Unix socket."""

    def __init__(
        self,
        socket_path: Path = DEFAULT_CONTROL_SOCKET,
        timeout_seconds: float = DEFAULT_CONTROL_TIMEOUT_SECONDS,
    ) -> None:
        self.socket_path = socket_path
        self.timeout_seconds = timeout_seconds

    def status(self) -> ControlResponse:
        """Request current provider and gateway status."""
        return self.request(
            StatusRequest(version=PROTOCOL_VERSION, request_id=uuid4(), operation=Operation.STATUS)
        )

    def targets(self) -> ControlResponse:
        """Request the sanitized configured target catalogue."""
        return self.request(
            TargetsRequest(
                version=PROTOCOL_VERSION,
                request_id=uuid4(),
                operation=Operation.TARGETS,
            )
        )

    def connect(self, target: str) -> ControlResponse:
        """Connect to a configured target alias."""
        return self.request(
            ConnectRequest(
                version=PROTOCOL_VERSION,
                request_id=uuid4(),
                operation=Operation.CONNECT,
                target=target,
            )
        )

    def disconnect(self) -> ControlResponse:
        """Safely disconnect the upstream VPN."""
        return self.request(
            DisconnectRequest(
                version=PROTOCOL_VERSION,
                request_id=uuid4(),
                operation=Operation.DISCONNECT,
            )
        )

    def protected(self, target: str) -> ControlResponse:
        """Enable protection and connect to a configured target."""
        return self.request(
            ProtectedRequest(
                version=PROTOCOL_VERSION,
                request_id=uuid4(),
                operation=Operation.PROTECTED,
                target=target,
            )
        )

    def lock(self) -> ControlResponse:
        """Enable protection and disconnect the upstream VPN."""
        return self.request(
            LockRequest(
                version=PROTOCOL_VERSION,
                request_id=uuid4(),
                operation=Operation.LOCK,
            )
        )

    def direct(self, confirmation_token: Literal["EXPOSE VPS IP"]) -> ControlResponse:
        """Disable protection and disconnect after explicit confirmation."""
        return self.request(
            DirectRequest(
                version=PROTOCOL_VERSION,
                request_id=uuid4(),
                operation=Operation.DIRECT,
                confirmation_token=confirmation_token,
            )
        )

    def target_schema(self, provider: str) -> ControlResponse:
        """Request the reviewed structured-selector schema for a provider."""
        return self.request(
            TargetSchemaRequest(
                version=PROTOCOL_VERSION,
                request_id=uuid4(),
                operation=Operation.TARGET_SCHEMA,
                provider=provider,
            )
        )

    def editable_catalogue(self, provider: str) -> ControlResponse:
        """Request the privileged editable catalogue for a provider."""
        return self.request(
            TargetCatalogGetRequest(
                version=PROTOCOL_VERSION,
                request_id=uuid4(),
                operation=Operation.TARGET_CATALOG_GET,
                provider=provider,
            )
        )

    def replace_catalogue(
        self,
        provider: str,
        expected_revision: int,
        targets: tuple[StoredTarget, ...],
    ) -> ControlResponse:
        """Atomically replace a provider catalogue."""
        return self.request(
            TargetCatalogReplaceRequest(
                version=PROTOCOL_VERSION,
                request_id=uuid4(),
                operation=Operation.TARGET_CATALOG_REPLACE,
                provider=provider,
                expected_revision=expected_revision,
                targets=targets,
            )
        )

    def request(self, request: ControlRequest) -> ControlResponse:
        """Exchange one framed request and correlated response."""
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(self.timeout_seconds)
                connection.connect(str(self.socket_path))
                connection.sendall(encode_message(request))
                response = parse_response(receive_frame(connection))
        except FileNotFoundError as exc:
            raise ControlClientError(
                "DAEMON_UNAVAILABLE",
                f"control socket does not exist: {self.socket_path}",
            ) from exc
        except PermissionError as exc:
            raise ControlClientError(
                "ACCESS_DENIED",
                f"permission denied opening control socket: {self.socket_path}",
            ) from exc
        except (ConnectionRefusedError, ConnectionResetError) as exc:
            raise ControlClientError(
                "DAEMON_UNAVAILABLE",
                "control daemon is not accepting connections",
            ) from exc
        except TimeoutError as exc:
            raise ControlClientError(
                "DAEMON_TIMEOUT", "control daemon did not respond in time"
            ) from exc
        except ProtocolError as exc:
            raise ControlClientError("INVALID_RESPONSE", str(exc)) from exc
        except OSError as exc:
            raise ControlClientError("SOCKET_ERROR", f"control socket error: {exc}") from exc

        if response.request_id != request.request_id:
            raise ControlClientError(
                "MISMATCHED_RESPONSE",
                "control response request ID does not match the request",
            )
        return response

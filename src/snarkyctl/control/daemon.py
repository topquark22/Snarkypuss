"""Socket-activated skeleton for the privileged SnarkyCtl control daemon.

This initial implementation deliberately performs no privileged operation. It
validates the activation environment, verifies the connecting UID, validates a
protocol request, and returns NOT_IMPLEMENTED.
"""

from __future__ import annotations

import logging
import os
import pwd
import socket
import struct
from contextlib import closing

from snarkyctl.control.protocol import (
    ControlResponse,
    ProtocolError,
    encode_message,
    parse_request,
    receive_frame,
)

LOGGER = logging.getLogger("snarkyctl.control")
SYSTEMD_FIRST_SOCKET_FD = 3
CONTROL_IO_TIMEOUT_SECONDS = 5.0
_PEER_CREDENTIALS = struct.Struct("3i")


class ActivationError(RuntimeError):
    """Raised when the daemon was not started with one systemd socket."""


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


def handle_connection(connection: socket.socket, permitted_uids: frozenset[int]) -> None:
    """Validate one request and return a safe placeholder response."""
    connection.settimeout(CONTROL_IO_TIMEOUT_SECONDS)
    pid, uid, _gid = peer_credentials(connection)
    if uid not in permitted_uids:
        LOGGER.warning("rejected unauthorized control peer pid=%d uid=%d", pid, uid)
        return

    try:
        request = parse_request(receive_frame(connection))
        response = ControlResponse(
            version=1,
            request_id=request.request_id,
            success=False,
            error_code="NOT_IMPLEMENTED",
            message="Privileged operations are not implemented yet.",
        )
        connection.sendall(encode_message(response))
    except (OSError, ProtocolError) as exc:
        LOGGER.warning("rejected invalid control request pid=%d uid=%d: %s", pid, uid, exc)


def serve(listener: socket.socket) -> None:  # pragma: no cover - integration loop
    """Serve validated local requests until systemd stops the process."""
    permitted_uids = allowed_uids()
    LOGGER.info("SnarkyCtl control daemon ready")
    while True:
        connection, _address = listener.accept()
        with closing(connection):
            handle_connection(connection, permitted_uids)


def main() -> int:  # pragma: no cover - exercised by systemd integration tests
    """Run the socket-activated control daemon."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    with closing(systemd_listener()) as listener:
        serve(listener)
    return 0


if __name__ == "__main__":  # pragma: no cover - console execution guard
    raise SystemExit(main())

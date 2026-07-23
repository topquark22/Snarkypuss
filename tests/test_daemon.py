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
    ControlResponse,
    Operation,
    StatusRequest,
    encode_message,
    receive_frame,
)

REQUEST_ID = UUID("0de2718e-98b1-43a0-879f-867d87b81a75")


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


def test_valid_request_receives_safe_placeholder_response() -> None:
    server, client = socket.socketpair()
    request = StatusRequest(version=1, request_id=REQUEST_ID, operation=Operation.STATUS)
    try:
        client.sendall(encode_message(request))
        daemon.handle_connection(server, frozenset({os.getuid()}))
        response = ControlResponse.model_validate_json(receive_frame(client))
    finally:
        server.close()
        client.close()

    assert response.request_id == REQUEST_ID
    assert response.success is False
    assert response.error_code == "NOT_IMPLEMENTED"


def test_unauthorized_peer_is_rejected() -> None:
    server, client = socket.socketpair()
    try:
        daemon.handle_connection(server, frozenset())
    finally:
        server.close()
        client.close()


def test_invalid_request_is_rejected_without_response() -> None:
    server, client = socket.socketpair()
    try:
        client.sendall(b"\x00\x00\x00\x03bad")
        daemon.handle_connection(server, frozenset({os.getuid()}))
    finally:
        server.close()
        client.close()

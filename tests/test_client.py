"""Tests for the unprivileged control-daemon client."""

import socket
from collections.abc import Iterator
from uuid import UUID

import pytest

from snarkyctl.control.client import ControlClient, ControlClientError
from snarkyctl.control.protocol import (
    ControlResponse,
    Operation,
    encode_message,
    parse_request,
)

REQUEST_ID = UUID("0de2718e-98b1-43a0-879f-867d87b81a75")


class FakeSocket:
    def __init__(self, response: ControlResponse) -> None:
        self.response = iter_chunks(encode_message(response))
        self.sent = b""
        self.path = ""
        self.timeout = 0.0

    def __enter__(self) -> "FakeSocket":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def settimeout(self, timeout: float) -> None:
        self.timeout = timeout

    def connect(self, path: str) -> None:
        self.path = path

    def sendall(self, payload: bytes) -> None:
        self.sent = payload

    def recv(self, size: int) -> bytes:
        return next(self.response, b"")[:size]


def iter_chunks(data: bytes) -> Iterator[bytes]:
    yield data[:4]
    yield data[4:]


def test_status_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSocket(
        ControlResponse(request_id=REQUEST_ID, success=True, message="ok")
    )
    monkeypatch.setattr("snarkyctl.control.client.uuid4", lambda: REQUEST_ID)
    monkeypatch.setattr(socket, "socket", lambda *_args: fake)

    response = ControlClient().status()

    assert response.success
    assert fake.path == "/run/snarkyctl/control.sock"
    request = parse_request(fake.sent[4:])
    assert request.operation is Operation.STATUS


def test_mismatched_response_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSocket(
        ControlResponse(
            request_id=UUID("b114fdb3-a593-4484-a1eb-da6262f53de2"),
            success=True,
            message="ok",
        )
    )
    monkeypatch.setattr("snarkyctl.control.client.uuid4", lambda: REQUEST_ID)
    monkeypatch.setattr(socket, "socket", lambda *_args: fake)

    with pytest.raises(ControlClientError, match="request ID") as exc_info:
        ControlClient().disconnect()
    assert exc_info.value.code == "MISMATCHED_RESPONSE"


def test_missing_socket_is_controlled(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(*_args: object) -> socket.socket:
        raise FileNotFoundError

    monkeypatch.setattr(socket, "socket", missing)
    with pytest.raises(ControlClientError) as exc_info:
        ControlClient().connect("dallas")
    assert exc_info.value.code == "DAEMON_UNAVAILABLE"

"""Tests for the privileged control protocol."""

import json
import socket
import struct
from uuid import UUID

import pytest

from snarkyctl.control.protocol import (
    MAX_MESSAGE_SIZE,
    PROTOCOL_VERSION,
    ConnectRequest,
    ControlResponse,
    Operation,
    ProtocolError,
    StatusRequest,
    encode_message,
    parse_request,
    receive_frame,
)
from snarkyctl.providers.base import VpnState, VpnStatus

REQUEST_ID = "0de2718e-98b1-43a0-879f-867d87b81a75"


def request_bytes(operation: str, **fields: object) -> bytes:
    value = {
        "version": PROTOCOL_VERSION,
        "request_id": REQUEST_ID,
        "operation": operation,
        **fields,
    }
    return json.dumps(value).encode()


def test_parse_status_request() -> None:
    request = parse_request(request_bytes("STATUS"))

    assert isinstance(request, StatusRequest)
    assert request.operation is Operation.STATUS


def test_parse_connect_request_with_approved_alias_shape() -> None:
    request = parse_request(request_bytes("CONNECT", target="dallas"))

    assert isinstance(request, ConnectRequest)
    assert request.target == "dallas"


@pytest.mark.parametrize(
    "payload",
    [
        request_bytes("SHELL", command="id"),
        request_bytes("CONNECT", target="Dallas, United States"),
        request_bytes("CONNECT", target="../../bin/sh"),
        request_bytes("STATUS", unexpected=True),
        request_bytes("STATUS").replace(b'"version": 1', b'"version": 2'),
        b"[]",
        b"not json",
        b"",
    ],
)
def test_invalid_requests_are_rejected(payload: bytes) -> None:
    with pytest.raises(ProtocolError):
        parse_request(payload)


def test_oversized_request_is_rejected() -> None:
    with pytest.raises(ProtocolError, match="maximum size"):
        parse_request(b"x" * (MAX_MESSAGE_SIZE + 1))


def test_size_prefixed_response_round_trip() -> None:
    response = ControlResponse(
        request_id=UUID(REQUEST_ID),
        success=False,
        error_code="NOT_IMPLEMENTED",
        message="Not implemented.",
        vpn_status=VpnStatus(state=VpnState.DISCONNECTED, provider="nordvpn"),
    )
    sender, receiver = socket.socketpair()
    try:
        sender.sendall(encode_message(response))
        payload = receive_frame(receiver)
    finally:
        sender.close()
        receiver.close()

    decoded = json.loads(payload)
    assert decoded["request_id"] == REQUEST_ID
    assert decoded["error_code"] == "NOT_IMPLEMENTED"
    assert decoded["vpn_status"]["state"] == "DISCONNECTED"


def test_declared_oversized_frame_is_rejected() -> None:
    sender, receiver = socket.socketpair()
    try:
        sender.sendall(struct.pack("!I", MAX_MESSAGE_SIZE + 1))
        with pytest.raises(ProtocolError, match="maximum size"):
            receive_frame(receiver)
    finally:
        sender.close()
        receiver.close()


def test_zero_length_frame_is_rejected() -> None:
    sender, receiver = socket.socketpair()
    try:
        sender.sendall(struct.pack("!I", 0))
        with pytest.raises(ProtocolError, match="empty"):
            receive_frame(receiver)
    finally:
        sender.close()
        receiver.close()


def test_incomplete_frame_is_rejected() -> None:
    sender, receiver = socket.socketpair()
    try:
        sender.sendall(struct.pack("!I", 10) + b"short")
        sender.shutdown(socket.SHUT_WR)
        with pytest.raises(ProtocolError, match="closed"):
            receive_frame(receiver)
    finally:
        sender.close()
        receiver.close()


def test_oversized_response_is_rejected() -> None:
    response = ControlResponse(
        request_id=UUID(REQUEST_ID),
        success=False,
        message="x" * MAX_MESSAGE_SIZE,
    )

    with pytest.raises(ProtocolError, match="response payload"):
        encode_message(response)

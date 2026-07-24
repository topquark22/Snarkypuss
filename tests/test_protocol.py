"""Tests for the privileged control protocol."""

import json
import socket
import struct
from datetime import UTC, datetime
from uuid import UUID

import pytest

from snarkyctl.control.protocol import (
    MAX_MESSAGE_SIZE,
    PROTOCOL_VERSION,
    ConnectRequest,
    ControlResponse,
    DirectRequest,
    Operation,
    ProtocolError,
    ProtectedRequest,
    StatusRequest,
    TargetCatalogGetRequest,
    TargetCatalogReplaceRequest,
    TargetSchemaRequest,
    TargetsRequest,
    encode_message,
    parse_request,
    parse_response,
    receive_frame,
)
from snarkyctl.targets.models import StoredTarget
from snarkyctl.providers.base import (
    ProviderCapabilities,
    VpnState,
    VpnStatus,
    VpnTargetCatalog,
    VpnTargetSummary,
)
from snarkyctl.status import GatewayStatus

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


def test_parse_targets_request() -> None:
    request = parse_request(request_bytes("TARGETS"))

    assert isinstance(request, TargetsRequest)
    assert request.operation is Operation.TARGETS


def test_parse_connect_request_with_approved_alias_shape() -> None:
    request = parse_request(request_bytes("CONNECT", target="dallas"))

    assert isinstance(request, ConnectRequest)
    assert request.target == "dallas"


def test_parse_protected_and_confirmed_direct_requests() -> None:
    protected = parse_request(request_bytes("PROTECTED", target="dallas"))
    direct = parse_request(
        request_bytes("DIRECT", confirmation_token="EXPOSE VPS IP")
    )

    assert isinstance(protected, ProtectedRequest)
    assert protected.target == "dallas"
    assert isinstance(direct, DirectRequest)


@pytest.mark.parametrize(
    "payload",
    [
        request_bytes("SHELL", command="id"),
        request_bytes("CONNECT", target="Dallas, United States"),
        request_bytes("CONNECT", target="../../bin/sh"),
        request_bytes("DIRECT", confirmation_token="yes"),
        request_bytes("STATUS", unexpected=True),
        json.dumps(
            {
                "version": PROTOCOL_VERSION - 1,
                "request_id": REQUEST_ID,
                "operation": "STATUS",
            }
        ).encode(),
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


def test_parse_target_administration_requests() -> None:
    schema = parse_request(request_bytes("TARGET_SCHEMA", provider="nordvpn"))
    catalogue = parse_request(request_bytes("TARGET_CATALOG_GET", provider="nordvpn"))
    replacement = parse_request(
        request_bytes(
            "TARGET_CATALOG_REPLACE",
            provider="nordvpn",
            expected_revision=2,
            targets=[
                {
                    "alias": "dallas",
                    "label": "Dallas",
                    "position": 0,
                    "selector": {"kind": "city", "country": "us", "city": "Dallas"},
                }
            ],
        )
    )
    assert isinstance(schema, TargetSchemaRequest)
    assert isinstance(catalogue, TargetCatalogGetRequest)
    assert isinstance(replacement, TargetCatalogReplaceRequest)
    assert replacement.targets[0].alias == "dallas"


@pytest.mark.parametrize(
    "payload",
    [
        request_bytes("TARGET_SCHEMA", provider="NordVPN"),
        request_bytes("TARGET_CATALOG_GET", provider="nordvpn", unexpected=True),
        request_bytes(
            "TARGET_CATALOG_REPLACE",
            provider="nordvpn",
            expected_revision=-1,
            targets=[],
        ),
        request_bytes(
            "TARGET_CATALOG_REPLACE",
            provider="nordvpn",
            expected_revision=0,
            targets=[
                StoredTarget(
                    alias=f"target_{index:03}",
                    label="Target",
                    position=index,
                    selector={"kind": "recommended"},
                ).model_dump()
                for index in range(100)
            ]
            + [
                {
                    "alias": "overflow",
                    "label": "Overflow",
                    "position": 0,
                    "selector": {"kind": "recommended"},
                }
            ],
        ),
    ],
)
def test_invalid_target_administration_requests_are_rejected(payload: bytes) -> None:
    with pytest.raises(ProtocolError):
        parse_request(payload)


def test_size_prefixed_response_round_trip() -> None:
    response = ControlResponse(
        request_id=UUID(REQUEST_ID),
        success=False,
        error_code="NOT_IMPLEMENTED",
        message="Not implemented.",
        vpn_status=VpnStatus(state=VpnState.DISCONNECTED, provider="nordvpn"),
        gateway_status=GatewayStatus(
            checked_at=datetime.now(UTC),
            vpn_status=VpnStatus(state=VpnState.DISCONNECTED, provider="nordvpn"),
            dns=None,
            system=None,
        ),
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
    assert decoded["gateway_status"]["vpn_status"]["provider"] == "nordvpn"
    assert parse_response(payload) == response


def test_maximum_configured_target_catalogue_fits_control_frame() -> None:
    response = ControlResponse(
        request_id=UUID(REQUEST_ID),
        success=True,
        message="ok",
        target_catalog=VpnTargetCatalog(
            provider="provider",
            capabilities=ProviderCapabilities(
                connect=True,
                disconnect=True,
                target_selection=True,
                server_details=True,
            ),
            targets=tuple(
                VpnTargetSummary(alias=f"target_{index:03}", label="x" * 100)
                for index in range(100)
            ),
        ),
    )

    encoded = encode_message(response)

    assert len(encoded) <= MAX_MESSAGE_SIZE + 4


@pytest.mark.parametrize("payload", [b"", b"[]", b"not json", b'{"version":2}'])
def test_invalid_responses_are_rejected(payload: bytes) -> None:
    with pytest.raises(ProtocolError):
        parse_response(payload)


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

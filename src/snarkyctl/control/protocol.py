"""Strict wire protocol shared by the web service and root control daemon."""

from __future__ import annotations

import json
import socket
import struct
from enum import StrEnum
from typing import Annotated, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter, ValidationError

from snarkyctl.providers.base import VpnStatus

PROTOCOL_VERSION: Final = 1
MAX_MESSAGE_SIZE = 4096
_FRAME_HEADER = struct.Struct("!I")

type RequestId = UUID
type TargetAlias = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9_-]{0,31}$"),
]
type ConfirmationToken = Annotated[
    str,
    StringConstraints(min_length=16, max_length=128),
]


class ProtocolError(ValueError):
    """Raised when a control-protocol message is invalid."""


class Operation(StrEnum):
    """Operations recognized by the privileged control daemon."""

    STATUS = "STATUS"
    LOCK = "LOCK"
    CONNECT = "CONNECT"
    DISCONNECT = "DISCONNECT"
    DIRECT = "DIRECT"


class _RequestBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1]
    request_id: RequestId


class StatusRequest(_RequestBase):
    operation: Literal[Operation.STATUS]


class LockRequest(_RequestBase):
    operation: Literal[Operation.LOCK]


class ConnectRequest(_RequestBase):
    operation: Literal[Operation.CONNECT]
    target: TargetAlias


class DisconnectRequest(_RequestBase):
    operation: Literal[Operation.DISCONNECT]


class DirectRequest(_RequestBase):
    operation: Literal[Operation.DIRECT]
    confirmation_token: ConfirmationToken


type ControlRequest = Annotated[
    StatusRequest | LockRequest | ConnectRequest | DisconnectRequest | DirectRequest,
    Field(discriminator="operation"),
]

_REQUEST_ADAPTER: TypeAdapter[ControlRequest] = TypeAdapter(ControlRequest)


class ControlResponse(BaseModel):
    """Structured response sent by the privileged control daemon."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1] = 1
    request_id: RequestId
    success: bool
    error_code: str | None = None
    message: str
    vpn_status: VpnStatus | None = None


def parse_request(payload: bytes) -> ControlRequest:
    """Decode and strictly validate one JSON request payload."""
    if not payload:
        raise ProtocolError("request payload is empty")
    if len(payload) > MAX_MESSAGE_SIZE:
        raise ProtocolError("request payload exceeds the maximum size")

    try:
        decoded = payload.decode("utf-8", errors="strict")
        value = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("request is not valid UTF-8 JSON") from exc

    if not isinstance(value, dict):
        raise ProtocolError("request must be a JSON object")

    try:
        return _REQUEST_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise ProtocolError("request does not match the control protocol") from exc


def parse_response(payload: bytes) -> ControlResponse:
    """Decode and strictly validate one JSON response payload."""
    value = _decode_payload(payload, "response")
    try:
        return ControlResponse.model_validate(value)
    except ValidationError as exc:
        raise ProtocolError("response does not match the control protocol") from exc


def _decode_payload(payload: bytes, message_type: str) -> dict[str, object]:
    if not payload:
        raise ProtocolError(f"{message_type} payload is empty")
    if len(payload) > MAX_MESSAGE_SIZE:
        raise ProtocolError(f"{message_type} payload exceeds the maximum size")
    try:
        value = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"{message_type} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ProtocolError(f"{message_type} must be a JSON object")
    return value


def encode_message(message: BaseModel) -> bytes:
    """Encode a model as a size-prefixed JSON frame."""
    payload = message.model_dump_json().encode("utf-8")
    if len(payload) > MAX_MESSAGE_SIZE:
        raise ProtocolError("response payload exceeds the maximum size")
    return _FRAME_HEADER.pack(len(payload)) + payload


def receive_frame(connection: socket.socket) -> bytes:
    """Receive one bounded, size-prefixed frame from a stream socket."""
    header = _receive_exact(connection, _FRAME_HEADER.size)
    (size,) = _FRAME_HEADER.unpack(header)
    if size == 0:
        raise ProtocolError("request payload is empty")
    if size > MAX_MESSAGE_SIZE:
        raise ProtocolError("request payload exceeds the maximum size")
    return _receive_exact(connection, size)


def _receive_exact(connection: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = connection.recv(remaining)
        if not chunk:
            raise ProtocolError("connection closed before the frame was complete")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)

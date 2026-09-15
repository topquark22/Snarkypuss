"""Minimal DNS health probe for the private Snarkypuss resolver."""

from __future__ import annotations

import random
import socket
import struct
from collections.abc import Callable

DNS_PORT = 53
DNS_PROBE_NAME = "example.com"
DNS_PROBE_TIMEOUT_SECONDS = 2.0
MAX_DNS_RESPONSE = 4096


type DnsExchange = Callable[[str, bytes, float], bytes]


def probe_dns(
    address: str,
    *,
    exchange: DnsExchange | None = None,
    timeout_seconds: float = DNS_PROBE_TIMEOUT_SECONDS,
) -> bool:
    """Return whether the private resolver returns a valid successful DNS response."""
    transaction_id = random.SystemRandom().randrange(0, 65536)
    query = _build_query(transaction_id)
    try:
        response = (exchange or _udp_exchange)(address, query, timeout_seconds)
    except OSError:
        return False
    return _valid_response(response, transaction_id)


def _build_query(transaction_id: int) -> bytes:
    header = struct.pack("!HHHHHH", transaction_id, 0x0100, 1, 0, 0, 0)
    labels = DNS_PROBE_NAME.split(".")
    question = b"".join(bytes((len(label),)) + label.encode("ascii") for label in labels)
    return header + question + b"\x00" + struct.pack("!HH", 1, 1)


def _udp_exchange(address: str, query: bytes, timeout_seconds: float) -> bytes:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.settimeout(timeout_seconds)
        probe.sendto(query, (address, DNS_PORT))
        response, source = probe.recvfrom(MAX_DNS_RESPONSE)
    if source[0] != address or source[1] != DNS_PORT:
        raise OSError("DNS response came from an unexpected endpoint")
    return response


def _valid_response(response: bytes, transaction_id: int) -> bool:
    if len(response) < 12:
        return False
    response_id, flags, questions, answers, _authority, _additional = struct.unpack(
        "!HHHHHH", response[:12]
    )
    is_response = bool(flags & 0x8000)
    truncated = bool(flags & 0x0200)
    rcode = flags & 0x000F
    return (
        response_id == transaction_id
        and is_response
        and not truncated
        and rcode == 0
        and questions == 1
        and answers > 0
    )

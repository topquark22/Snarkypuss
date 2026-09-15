"""Tests for the private DNS resolver health probe."""

import struct

from snarkyctl.dns_health import probe_dns


def response_for(query: bytes, *, flags: int = 0x8180, answers: int = 1) -> bytes:
    transaction_id = struct.unpack("!H", query[:2])[0]
    return struct.pack("!HHHHHH", transaction_id, flags, 1, answers, 0, 0)


def test_probe_accepts_successful_dns_response() -> None:
    def exchange(address: str, query: bytes, timeout: float) -> bytes:
        assert address == "10.8.0.1"
        assert timeout == 2.0
        return response_for(query)

    assert probe_dns("10.8.0.1", exchange=exchange)


def test_probe_reports_socket_failure() -> None:
    def exchange(_address: str, _query: bytes, _timeout: float) -> bytes:
        raise OSError("unavailable")

    assert not probe_dns("10.8.0.1", exchange=exchange)


def test_probe_rejects_wrong_transaction_id() -> None:
    def exchange(_address: str, query: bytes, _timeout: float) -> bytes:
        response = bytearray(response_for(query))
        response[0:2] = b"\x00\x00" if query[0:2] != b"\x00\x00" else b"\x00\x01"
        return bytes(response)

    assert not probe_dns("10.8.0.1", exchange=exchange)


def test_probe_rejects_dns_error_response() -> None:
    def exchange(_address: str, query: bytes, _timeout: float) -> bytes:
        return response_for(query, flags=0x8182)

    assert not probe_dns("10.8.0.1", exchange=exchange)


def test_probe_rejects_truncated_response() -> None:
    def exchange(_address: str, query: bytes, _timeout: float) -> bytes:
        return response_for(query, flags=0x8380)

    assert not probe_dns("10.8.0.1", exchange=exchange)


def test_probe_requires_an_answer() -> None:
    def exchange(_address: str, query: bytes, _timeout: float) -> bytes:
        return response_for(query, answers=0)

    assert not probe_dns("10.8.0.1", exchange=exchange)


def test_probe_rejects_short_response() -> None:
    def exchange(_address: str, _query: bytes, _timeout: float) -> bytes:
        return b"short"

    assert not probe_dns("10.8.0.1", exchange=exchange)

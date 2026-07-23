"""HTTP Basic credential verification backed by a local htpasswd file."""

from __future__ import annotations

import os
import secrets
import stat
from pathlib import Path

import bcrypt

MAX_AUTH_FILE_SIZE = 64 * 1024


class AuthFileError(RuntimeError):
    """The authentication file could not be read or safely interpreted."""


def verify_credentials(path: Path, username: str, password: str) -> bool:
    """Verify credentials against bcrypt records in a bounded regular file."""
    records = _read_records(path)
    supplied_username = username.encode("utf-8")
    supplied_password = password.encode("utf-8")
    matched = False
    for stored_username, password_hash in records:
        username_matches = secrets.compare_digest(supplied_username, stored_username)
        try:
            password_matches = bcrypt.checkpw(supplied_password, password_hash)
        except ValueError as exc:
            raise AuthFileError(f"invalid bcrypt record in {path}") from exc
        matched = matched or (username_matches and password_matches)
    return matched


def _read_records(path: Path) -> tuple[tuple[bytes, bytes], ...]:
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise AuthFileError(f"cannot open {path}: {exc.strerror}") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise AuthFileError(f"{path} is not a regular file")
        if metadata.st_size > MAX_AUTH_FILE_SIZE:
            raise AuthFileError(f"{path} exceeds the {MAX_AUTH_FILE_SIZE}-byte limit")
        with os.fdopen(descriptor, encoding="utf-8") as stream:
            descriptor = -1
            try:
                lines = stream.read().splitlines()
            except UnicodeError as exc:
                raise AuthFileError(f"{path} is not valid UTF-8") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    records: list[tuple[bytes, bytes]] = []
    for line in lines:
        if not line or line.startswith("#"):
            continue
        try:
            username, password_hash = line.split(":", 1)
        except ValueError as exc:
            raise AuthFileError(f"invalid htpasswd record in {path}") from exc
        if not username or not password_hash.startswith(("$2a$", "$2b$", "$2y$")):
            raise AuthFileError(f"invalid bcrypt htpasswd record in {path}")
        records.append((username.encode("utf-8"), password_hash.encode("ascii")))
    if not records:
        raise AuthFileError(f"{path} contains no credential records")
    return tuple(records)

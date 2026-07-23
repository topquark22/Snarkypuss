"""Tests for file-backed HTTP Basic credential verification."""

from pathlib import Path

import bcrypt
import pytest

from snarkyctl.auth import AuthFileError, verify_credentials


def write_auth(path: Path) -> None:
    password_hash = bcrypt.hashpw(b"correct horse", bcrypt.gensalt()).decode()
    path.write_text(f"admin:{password_hash}\n", encoding="utf-8")


def test_bcrypt_credentials_are_verified(tmp_path: Path) -> None:
    auth_file = tmp_path / "auth.htpasswd"
    write_auth(auth_file)

    assert verify_credentials(auth_file, "admin", "correct horse")
    assert not verify_credentials(auth_file, "admin", "wrong")
    assert not verify_credentials(auth_file, "somebody", "correct horse")


def test_invalid_auth_file_is_controlled(tmp_path: Path) -> None:
    auth_file = tmp_path / "auth.htpasswd"
    auth_file.write_text("admin:plaintext\n", encoding="utf-8")

    with pytest.raises(AuthFileError, match="bcrypt"):
        verify_credentials(auth_file, "admin", "password")


@pytest.mark.parametrize("contents", ["", "malformed\n"])
def test_empty_or_malformed_auth_file_is_rejected(tmp_path: Path, contents: str) -> None:
    auth_file = tmp_path / "auth.htpasswd"
    auth_file.write_text(contents, encoding="utf-8")

    with pytest.raises(AuthFileError):
        verify_credentials(auth_file, "admin", "password")


def test_missing_auth_file_is_controlled(tmp_path: Path) -> None:
    with pytest.raises(AuthFileError, match="cannot open"):
        verify_credentials(tmp_path / "missing", "admin", "password")


def test_invalid_bcrypt_hash_is_controlled(tmp_path: Path) -> None:
    auth_file = tmp_path / "auth.htpasswd"
    auth_file.write_text("admin:$2b$invalid\n", encoding="utf-8")

    with pytest.raises(AuthFileError, match="invalid bcrypt record"):
        verify_credentials(auth_file, "admin", "password")

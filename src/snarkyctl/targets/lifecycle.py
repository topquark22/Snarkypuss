"""Secure lifecycle operations for the target catalogue database."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from snarkyctl.targets.repository import RepositoryError
from snarkyctl.targets.sqlite import SqliteTargetRepository

DEFAULT_TARGET_DATABASE_PATH = Path("/var/lib/snarkyctl/targets.db")
DATABASE_MODE = 0o600
DIRECTORY_MODE = 0o700


def _is_production(path: Path) -> bool:
    return path == DEFAULT_TARGET_DATABASE_PATH


def _require_root(path: Path) -> None:
    if _is_production(path) and os.geteuid() != 0:
        raise RepositoryError(
            "ROOT_REQUIRED",
            f"Root privileges are required for the production database {path}.",
        )


def _check_path(path: Path) -> os.stat_result:
    try:
        result = path.lstat()
    except FileNotFoundError as exc:
        raise RepositoryError("DATABASE_NOT_FOUND", f"Database does not exist: {path}") from exc
    if stat.S_ISLNK(result.st_mode):
        raise RepositoryError("UNSAFE_DATABASE_PATH", "Database path must not be a symbolic link.")
    if not stat.S_ISREG(result.st_mode):
        raise RepositoryError("UNSAFE_DATABASE_PATH", "Database path must be a regular file.")
    if _is_production(path):
        if result.st_uid != 0 or result.st_gid != 0:
            raise RepositoryError("UNSAFE_DATABASE_OWNER", "Production database must be root-owned.")
        if stat.S_IMODE(result.st_mode) != DATABASE_MODE:
            raise RepositoryError(
                "UNSAFE_DATABASE_MODE", "Production database permissions must be 0600."
            )
    return result


def initialize_database(path: Path = DEFAULT_TARGET_DATABASE_PATH) -> SqliteTargetRepository:
    """Securely initialize an empty catalogue database."""
    _require_root(path)
    if path.is_symlink():
        raise RepositoryError("UNSAFE_DATABASE_PATH", "Database path must not be a symbolic link.")
    if path.exists():
        raise RepositoryError("DATABASE_EXISTS", f"Database already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True, mode=DIRECTORY_MODE)
    if _is_production(path):
        parent = path.parent.lstat()
        if stat.S_ISLNK(parent.st_mode) or not stat.S_ISDIR(parent.st_mode):
            raise RepositoryError("UNSAFE_DATABASE_PATH", "Database directory is unsafe.")
        os.chown(path.parent, 0, 0)
        os.chmod(path.parent, DIRECTORY_MODE)
    repository = SqliteTargetRepository.initialize(path)
    os.chmod(path, DATABASE_MODE)
    if _is_production(path):
        os.chown(path, 0, 0)
    _check_path(path)
    repository.integrity_check()
    return repository


def check_database(path: Path = DEFAULT_TARGET_DATABASE_PATH) -> None:
    """Check path security, schema compatibility, and SQLite integrity."""
    _require_root(path)
    _check_path(path)
    SqliteTargetRepository(path).integrity_check()


def backup_database(
    destination: Path,
    source: Path = DEFAULT_TARGET_DATABASE_PATH,
) -> None:
    """Create a consistent, restrictive backup."""
    _require_root(source)
    _check_path(source)
    if destination.is_symlink():
        raise RepositoryError("UNSAFE_DATABASE_PATH", "Backup path must not be a symbolic link.")
    SqliteTargetRepository(source).backup(destination)
    os.chmod(destination, DATABASE_MODE)

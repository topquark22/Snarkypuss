"""Tests for SQLite target storage and lifecycle operations."""

import os
import sqlite3
from pathlib import Path

import pytest

from snarkyctl.targets.lifecycle import backup_database, check_database, initialize_database
from snarkyctl.targets.models import StoredTarget
from snarkyctl.targets.repository import RepositoryError
from snarkyctl.targets.sqlite import SqliteTargetRepository


def target(alias: str, position: int) -> StoredTarget:
    return StoredTarget(
        alias=alias,
        label=alias.title(),
        position=position,
        selector={"kind": "country", "country": alias},
    )


def test_initialize_empty_database_and_persist_after_reopen(tmp_path: Path) -> None:
    path = tmp_path / "targets.db"
    repository = initialize_database(path)
    assert repository.get_catalogue("nordvpn").targets == ()
    saved = repository.replace_catalogue(
        "nordvpn", 0, (target("canada", 0), target("france", 1))
    )
    reopened = SqliteTargetRepository(path)
    assert reopened.get_catalogue("nordvpn") == saved
    assert os.stat(path).st_mode & 0o777 == 0o600


def test_complete_replacement_increments_revision_and_preserves_order(tmp_path: Path) -> None:
    repository = initialize_database(tmp_path / "targets.db")
    first = repository.replace_catalogue("nordvpn", 0, (target("canada", 0),))
    second = repository.replace_catalogue(
        "nordvpn", first.revision, (target("france", 0), target("canada", 1))
    )
    assert second.revision == 2
    assert [item.alias for item in second.targets] == ["france", "canada"]


def test_stale_revision_rolls_back_complete_replacement(tmp_path: Path) -> None:
    repository = initialize_database(tmp_path / "targets.db")
    saved = repository.replace_catalogue("nordvpn", 0, (target("canada", 0),))
    with pytest.raises(RepositoryError) as error:
        repository.replace_catalogue("nordvpn", 0, (target("france", 0),))
    assert error.value.code == "CATALOG_CONFLICT"
    assert repository.get_catalogue("nordvpn") == saved


def test_provider_catalogues_are_independent(tmp_path: Path) -> None:
    repository = initialize_database(tmp_path / "targets.db")
    repository.replace_catalogue("nordvpn", 0, (target("canada", 0),))
    repository.replace_catalogue("other", 0, (target("france", 0),))
    assert repository.get_catalogue("nordvpn").targets[0].alias == "canada"
    assert repository.get_catalogue("other").targets[0].alias == "france"


def test_model_rejects_duplicate_aliases_and_positions_before_sql(tmp_path: Path) -> None:
    repository = initialize_database(tmp_path / "targets.db")
    with pytest.raises(ValueError):
        repository.replace_catalogue("nordvpn", 0, (target("same", 0), target("same", 1)))
    with pytest.raises(ValueError):
        repository.replace_catalogue("nordvpn", 0, (target("one", 0), target("two", 0)))


def test_unsupported_or_corrupt_schema_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "targets.db"
    sqlite3.connect(path).close()
    with pytest.raises(RepositoryError) as error:
        SqliteTargetRepository(path)
    assert error.value.code == "UNSUPPORTED_SCHEMA"


def test_database_lock_honors_timeout_and_preserves_catalogue(tmp_path: Path) -> None:
    path = tmp_path / "targets.db"
    repository = initialize_database(path)
    lock = sqlite3.connect(path)
    lock.execute("BEGIN IMMEDIATE")
    try:
        fast_repository = SqliteTargetRepository(path, busy_timeout_ms=1)
        with pytest.raises(RepositoryError) as error:
            fast_repository.replace_catalogue("nordvpn", 0, (target("canada", 0),))
        assert error.value.code == "CATALOG_STORAGE_FAILED"
    finally:
        lock.rollback()
        lock.close()
    assert repository.get_catalogue("nordvpn").targets == ()


def test_consistent_backup_can_be_checked_and_read(tmp_path: Path) -> None:
    source = tmp_path / "targets.db"
    destination = tmp_path / "targets.backup.db"
    repository = initialize_database(source)
    repository.replace_catalogue("nordvpn", 0, (target("canada", 0),))
    backup_database(destination, source)
    check_database(destination)
    assert SqliteTargetRepository(destination).get_catalogue("nordvpn").revision == 1


def test_lifecycle_rejects_symlink(tmp_path: Path) -> None:
    real = tmp_path / "real.db"
    initialize_database(real)
    link = tmp_path / "link.db"
    link.symlink_to(real)
    with pytest.raises(RepositoryError) as error:
        check_database(link)
    assert error.value.code == "UNSAFE_DATABASE_PATH"

"""SQLite implementation of the target repository."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from pydantic import ValidationError

from snarkyctl.targets.models import StoredTarget, TargetCatalogue
from snarkyctl.targets.repository import RepositoryError, TargetRepository

SCHEMA_VERSION = 1
MAX_SELECTOR_JSON_BYTES = 4096

SCHEMA = """
CREATE TABLE schema_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
) STRICT;
CREATE TABLE provider_catalogues (
    provider TEXT PRIMARY KEY,
    revision INTEGER NOT NULL CHECK (revision >= 0)
) STRICT;
CREATE TABLE targets (
    provider TEXT NOT NULL,
    alias TEXT NOT NULL,
    label TEXT NOT NULL,
    position INTEGER NOT NULL CHECK (position >= 0),
    selector_json TEXT NOT NULL CHECK (length(selector_json) <= 4096),
    PRIMARY KEY (provider, alias),
    UNIQUE (provider, position),
    FOREIGN KEY (provider) REFERENCES provider_catalogues(provider) ON DELETE CASCADE
) STRICT;
"""


class SqliteTargetRepository(TargetRepository):
    """Transactional SQLite catalogue repository."""

    def __init__(self, path: Path, *, busy_timeout_ms: int = 5000) -> None:
        self.path = path
        self.busy_timeout_ms = busy_timeout_ms
        self._verify_schema()

    @classmethod
    def initialize(cls, path: Path, *, busy_timeout_ms: int = 5000) -> SqliteTargetRepository:
        """Create a new empty database and return its repository."""
        if path.exists():
            raise RepositoryError("DATABASE_EXISTS", f"Database already exists: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA synchronous = FULL")
            connection.executescript(SCHEMA)
            connection.execute(
                "INSERT INTO schema_metadata (key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            connection.commit()
        except sqlite3.Error as exc:
            connection.rollback()
            raise RepositoryError("DATABASE_INITIALIZATION_FAILED", str(exc)) from exc
        finally:
            connection.close()
        return cls(path, busy_timeout_ms=busy_timeout_ms)

    def _connect(self) -> sqlite3.Connection:
        try:
            connection = sqlite3.connect(self.path, timeout=self.busy_timeout_ms / 1000)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
            return connection
        except sqlite3.Error as exc:
            raise RepositoryError("CATALOG_STORAGE_FAILED", str(exc)) from exc

    def _verify_schema(self) -> None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT value FROM schema_metadata WHERE key = 'schema_version'"
                ).fetchone()
        except (sqlite3.Error, RepositoryError) as exc:
            raise RepositoryError("UNSUPPORTED_SCHEMA", "Database schema is missing or corrupt.") from exc
        if row is None or row["value"] != str(SCHEMA_VERSION):
            raise RepositoryError("UNSUPPORTED_SCHEMA", "Database schema version is unsupported.")

    def integrity_check(self) -> None:
        with self._connect() as connection:
            result = connection.execute("PRAGMA integrity_check").fetchone()
        if result is None or result[0] != "ok":
            raise RepositoryError("DATABASE_INTEGRITY_FAILED", "SQLite integrity check failed.")

    def get_catalogue(self, provider: str) -> TargetCatalogue:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT revision FROM provider_catalogues WHERE provider = ?", (provider,)
                ).fetchone()
                if row is None:
                    return TargetCatalogue(provider=provider, revision=0, targets=())
                target_rows = connection.execute(
                    """
                    SELECT alias, label, position, selector_json
                    FROM targets WHERE provider = ? ORDER BY position
                    """,
                    (provider,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise RepositoryError("CATALOG_STORAGE_FAILED", str(exc)) from exc
        try:
            targets = tuple(
                StoredTarget(
                    alias=item["alias"],
                    label=item["label"],
                    position=item["position"],
                    selector=json.loads(item["selector_json"]),
                )
                for item in target_rows
            )
            return TargetCatalogue(provider=provider, revision=row["revision"], targets=targets)
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            raise RepositoryError("CATALOG_STORAGE_FAILED", "Stored catalogue is invalid.") from exc

    def replace_catalogue(
        self,
        provider: str,
        expected_revision: int,
        targets: tuple[StoredTarget, ...],
    ) -> TargetCatalogue:
        candidate = TargetCatalogue(provider=provider, revision=expected_revision + 1, targets=targets)
        encoded = [
            json.dumps(target.selector, sort_keys=True, separators=(",", ":"))
            for target in candidate.targets
        ]
        if any(len(value.encode()) > MAX_SELECTOR_JSON_BYTES for value in encoded):
            raise RepositoryError("INVALID_CATALOG", "A selector document is too large.")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT revision FROM provider_catalogues WHERE provider = ?", (provider,)
            ).fetchone()
            current_revision = 0 if row is None else int(row["revision"])
            if current_revision != expected_revision:
                raise RepositoryError("CATALOG_CONFLICT", "Catalogue revision is stale.")
            if row is None:
                connection.execute(
                    "INSERT INTO provider_catalogues (provider, revision) VALUES (?, ?)",
                    (provider, candidate.revision),
                )
            else:
                connection.execute(
                    "UPDATE provider_catalogues SET revision = ? WHERE provider = ?",
                    (candidate.revision, provider),
                )
                connection.execute("DELETE FROM targets WHERE provider = ?", (provider,))
            connection.executemany(
                """
                INSERT INTO targets
                    (provider, alias, label, position, selector_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    (provider, target.alias, target.label, target.position, selector)
                    for target, selector in zip(candidate.targets, encoded, strict=True)
                ),
            )
            connection.commit()
            return candidate
        except RepositoryError:
            connection.rollback()
            raise
        except sqlite3.Error as exc:
            connection.rollback()
            raise RepositoryError("CATALOG_STORAGE_FAILED", str(exc)) from exc
        finally:
            connection.close()

    def backup(self, destination: Path) -> None:
        """Create a transactionally consistent SQLite backup."""
        if destination.exists():
            raise RepositoryError("BACKUP_EXISTS", f"Backup already exists: {destination}")
        source = self._connect()
        destination_connection = sqlite3.connect(destination)
        try:
            source.backup(destination_connection)
        except sqlite3.Error as exc:
            raise RepositoryError("DATABASE_BACKUP_FAILED", str(exc)) from exc
        finally:
            destination_connection.close()
            source.close()

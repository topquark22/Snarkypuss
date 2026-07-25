"""Archived one-time migration from the legacy YAML target catalogue to SQLite.

This module is retained only for early development deployments. It is not installed with
SnarkyCtl and is not exposed by the production CLI.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from snarkyctl.config import DEFAULT_CONFIG_PATH, ConfigError, load_config
from snarkyctl.providers.registry import create_provider
from snarkyctl.targets.lifecycle import (
    DEFAULT_TARGET_DATABASE_PATH,
    backup_database,
    check_database,
    initialize_database,
)
from snarkyctl.targets.models import StoredTarget
from snarkyctl.targets.repository import RepositoryError
from snarkyctl.targets.sqlite import SqliteTargetRepository


@dataclass(frozen=True)
class MigrationResult:
    """Result of one completed YAML-to-SQLite migration."""

    provider: str
    database: Path
    revision: int
    migrated_count: int
    yaml_backup: Path
    database_backup: Path | None


def migrate_yaml_catalogue(
    config_path: Path = DEFAULT_CONFIG_PATH,
    database_path: Path = DEFAULT_TARGET_DATABASE_PATH,
) -> MigrationResult:
    """Validate, back up, and atomically migrate the configured YAML catalogue."""
    loaded = load_config(config_path)
    targets_file = loaded.settings.upstream_vpn.targets_file
    if targets_file is None or loaded.targets is None:
        raise ConfigError("migration requires the legacy upstream_vpn.targets_file configuration")

    provider_name = loaded.settings.upstream_vpn.provider
    provider = create_provider(
        provider_name,
        timeout_seconds=loaded.settings.control.operation_timeout_seconds,
    )
    normalized = tuple(
        StoredTarget(
            alias=target.alias,
            label=target.label,
            position=position,
            selector=provider.import_legacy_target(target.provider_target),
        )
        for position, target in enumerate(loaded.targets.targets)
    )

    yaml_backup = targets_file.with_name(f"{targets_file.name}.pre-sqlite")
    if yaml_backup.exists() or yaml_backup.is_symlink():
        raise RepositoryError("BACKUP_EXISTS", f"YAML backup already exists: {yaml_backup}")

    database_backup: Path | None = None
    if database_path.exists() or database_path.is_symlink():
        check_database(database_path)
        repository = SqliteTargetRepository(database_path)
        current = repository.get_catalogue(provider_name)
        if current.revision != 0 or current.targets:
            raise RepositoryError(
                "CATALOG_ALREADY_INITIALIZED",
                "The SQLite catalogue is not empty; migration refused.",
            )
        database_backup = database_path.with_name(f"{database_path.name}.pre-migration")
        backup_database(database_backup, database_path)
    else:
        repository = initialize_database(database_path)

    shutil.copy2(targets_file, yaml_backup, follow_symlinks=False)
    catalogue = repository.replace_catalogue(provider_name, 0, normalized)
    repository.integrity_check()
    return MigrationResult(
        provider=provider_name,
        database=database_path,
        revision=catalogue.revision,
        migrated_count=len(catalogue.targets),
        yaml_backup=yaml_backup,
        database_backup=database_backup,
    )

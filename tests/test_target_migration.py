"""Tests for explicit YAML-to-SQLite catalogue migration."""

from pathlib import Path

import pytest

from snarkyctl.config import ConfigError
from snarkyctl.targets.migration import migrate_yaml_catalogue
from snarkyctl.targets.repository import RepositoryError
from snarkyctl.targets.sqlite import SqliteTargetRepository


def write_legacy_configuration(tmp_path: Path) -> Path:
    targets = tmp_path / "targets.yaml"
    targets.write_text(
        """schema_version: 1
targets:
  - alias: dallas
    label: Dallas
    provider_target: Dallas
  - alias: prague
    label: Prague
    provider_target: Prague
""",
        encoding="utf-8",
    )
    config = tmp_path / "snarkyctl.yaml"
    config.write_text(
        f"""schema_version: 1
network:
  management_interface: wg0
  management_address: 10.8.0.1/24
  client_subnet: 10.8.0.0/24
  public_interface: eth0
web:
  bind_address: 10.8.0.1
  port: 8443
  auth_file: /etc/snarkyctl/auth.htpasswd
  tls_certificate: /etc/snarkyctl/tls/server.crt
  tls_private_key: /etc/snarkyctl/tls/server.key
  request_timeout_seconds: 10
control:
  socket_path: /run/snarkyctl/control.sock
  operation_timeout_seconds: 60
upstream_vpn:
  provider: nordvpn
  expected_interfaces: [nordlynx]
  targets_file: {targets}
""",
        encoding="utf-8",
    )
    return config


def test_migration_preserves_aliases_labels_order_and_legacy_values(tmp_path: Path) -> None:
    config = write_legacy_configuration(tmp_path)
    database = tmp_path / "targets.db"
    result = migrate_yaml_catalogue(config, database)
    catalogue = SqliteTargetRepository(database).get_catalogue("nordvpn")
    assert result.revision == 1
    assert result.migrated_count == 2
    assert [target.alias for target in catalogue.targets] == ["dallas", "prague"]
    assert catalogue.targets[0].selector == {"kind": "legacy", "value": "Dallas"}
    assert result.yaml_backup.read_text(encoding="utf-8") == (
        tmp_path / "targets.yaml"
    ).read_text(encoding="utf-8")


def test_migration_backs_up_existing_empty_database(tmp_path: Path) -> None:
    config = write_legacy_configuration(tmp_path)
    database = tmp_path / "targets.db"
    SqliteTargetRepository.initialize(database)
    result = migrate_yaml_catalogue(config, database)
    assert result.database_backup is not None
    assert result.database_backup.exists()
    assert SqliteTargetRepository(result.database_backup).get_catalogue("nordvpn").revision == 0


def test_migration_refuses_nonempty_database_without_modifying_it(tmp_path: Path) -> None:
    config = write_legacy_configuration(tmp_path)
    database = tmp_path / "targets.db"
    repository = SqliteTargetRepository.initialize(database)
    from snarkyctl.targets.models import StoredTarget

    repository.replace_catalogue(
        "nordvpn",
        0,
        (
            StoredTarget(
                alias="existing",
                label="Existing",
                position=0,
                selector={"kind": "legacy", "value": "Canada"},
            ),
        ),
    )
    with pytest.raises(RepositoryError) as error:
        migrate_yaml_catalogue(config, database)
    assert error.value.code == "CATALOG_ALREADY_INITIALIZED"
    assert repository.get_catalogue("nordvpn").targets[0].alias == "existing"


def test_migration_requires_legacy_yaml_configuration(tmp_path: Path) -> None:
    config = write_legacy_configuration(tmp_path)
    text = config.read_text(encoding="utf-8").replace(
        f"  targets_file: {tmp_path / 'targets.yaml'}",
        f"  targets:\n    backend: sqlite\n    path: {tmp_path / 'targets.db'}",
    )
    config.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match="legacy"):
        migrate_yaml_catalogue(config, tmp_path / "other.db")

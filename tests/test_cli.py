"""Tests for the SnarkyCtl command-line entry point."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from snarkyctl import __version__
from snarkyctl.cli import main
from snarkyctl.control.client import ControlClientError
from snarkyctl.control.protocol import ControlResponse
from snarkyctl.preflight import CheckResult, CheckStatus, PreflightReport
from snarkyctl.providers.base import (
    GatewayMode,
    ProviderCapabilities,
    VpnState,
    VpnStatus,
    VpnTargetCatalog,
    VpnTargetSummary,
)
from snarkyctl.status import (
    ComponentFailure,
    DnsStatus,
    GatewayStatus,
    PublicIpStatus,
    SystemStatus,
)
from snarkyctl.targets.migration import MigrationResult
from snarkyctl.targets.models import (
    ProviderTargetSchema,
    SelectorKind,
    StoredTarget,
    TargetCatalogue,
)
from snarkyctl.targets.repository import RepositoryError


def test_version_option(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"snarkyctl {__version__}"


def test_no_arguments_succeeds() -> None:
    assert main([]) == 0


def test_validate_config_reports_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "missing.yaml"
    assert main(["validate-config", "--config", str(missing)]) == 2
    assert "cannot open" in capsys.readouterr().err


def test_preflight_json_and_failure_exit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    report = PreflightReport(
        checks=(CheckResult(check_id="test", status=CheckStatus.FAIL, message="failed"),)
    )
    monkeypatch.setattr("snarkyctl.cli.run_preflight", lambda _path: report)
    assert main(["preflight", "--json"]) == 1
    assert '"check_id": "test"' in capsys.readouterr().out


def test_preflight_config_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from snarkyctl.config import ConfigError

    def fail(_path: Path) -> PreflightReport:
        raise ConfigError("invalid")

    monkeypatch.setattr("snarkyctl.cli.run_preflight", fail)
    assert main(["preflight"]) == 2
    assert "invalid" in capsys.readouterr().err


def test_status_human_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    response = ControlResponse(
        request_id="0de2718e-98b1-43a0-879f-867d87b81a75",
        success=True,
        message="ok",
        gateway_status=GatewayStatus(
            checked_at=datetime.now(UTC),
            vpn_status=VpnStatus(
                state=VpnState.CONNECTED,
                provider="nordvpn",
                gateway_mode=GatewayMode.VPN,
                leak_protection_active=True,
                target="dallas",
            ),
            dns=None,
            system=None,
        ),
    )
    monkeypatch.setattr("snarkyctl.cli.ControlClient.status", lambda _self: response)

    assert main(["status"]) == 0
    output = capsys.readouterr().out
    assert "Gateway mode:     VPN" in output
    assert "Public exposure:  No" in output


def test_status_human_output_includes_local_components_and_failures(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    response = ControlResponse(
        request_id="0de2718e-98b1-43a0-879f-867d87b81a75",
        success=True,
        message="partial",
        gateway_status=GatewayStatus(
            checked_at=datetime.now(UTC),
            vpn_status=None,
            dns=DnsStatus(
                service="dnsmasq.service",
                load_state="loaded",
                active_state="active",
                sub_state="running",
            ),
            system=SystemStatus(
                uptime_seconds=183642,
                load_average=(0.08, 0.11, 0.09),
                memory_total_bytes=2 * 1024**3,
                memory_available_bytes=1024**3,
                root_disk_total_bytes=50 * 1024**3,
                root_disk_free_bytes=40 * 1024**3,
            ),
            public_ip=PublicIpStatus(
                address="203.0.113.42",
                checked_at=datetime.now(UTC),
            ),
            partial_failures=(
                ComponentFailure(
                    component="vpn",
                    code="PROVIDER_TIMEOUT",
                    message="provider timed out",
                ),
            ),
        ),
    )
    monkeypatch.setattr("snarkyctl.cli.ControlClient.status", lambda _self: response)

    assert main(["status"]) == 0
    output = capsys.readouterr().out
    assert "Upstream VPN\n  Status:          Unavailable" in output
    assert "active (running)" in output
    assert "2d 3h 0m" in output
    assert "1.0 GiB / 2.0 GiB" in output
    assert "Public exit IPv4: 203.0.113.42" in output
    assert "vpn: PROVIDER_TIMEOUT: provider timed out" in output


def test_connect_json_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    response = ControlResponse(
        request_id="0de2718e-98b1-43a0-879f-867d87b81a75",
        success=False,
        error_code="INVALID_TARGET",
        message="unknown target",
    )
    monkeypatch.setattr("snarkyctl.cli.ControlClient.connect", lambda _self, _target: response)

    assert main(["connect", "dallas", "--json"]) == 1
    assert '"error_code": "INVALID_TARGET"' in capsys.readouterr().out


def test_control_client_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(_self: object) -> ControlResponse:
        raise ControlClientError("DAEMON_UNAVAILABLE", "not running")

    monkeypatch.setattr("snarkyctl.cli.ControlClient.disconnect", fail)
    assert main(["disconnect"]) == 2
    assert "DAEMON_UNAVAILABLE" in capsys.readouterr().err


def test_targets_database_lifecycle_commands(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database = tmp_path / "targets.db"
    backup = tmp_path / "targets.backup.db"
    assert main(["targets-db", "initialize", "--database", str(database)]) == 0
    assert main(["targets-db", "check", "--database", str(database)]) == 0
    assert (
        main(
            [
                "targets-db",
                "backup",
                "--database",
                str(database),
                "--output",
                str(backup),
            ]
        )
        == 0
    )
    assert backup.exists()
    assert "Backed up" in capsys.readouterr().out


def test_targets_database_error_is_controlled(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(_path: Path) -> None:
        raise RepositoryError("DATABASE_NOT_FOUND", "missing")

    monkeypatch.setattr("snarkyctl.cli.check_database", fail)
    assert main(["targets-db", "check", "--database", "/tmp/missing.db"]) == 2
    assert "DATABASE_NOT_FOUND: missing" in capsys.readouterr().err


def test_targets_database_migrate_reports_yaml_remains_authoritative(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database = tmp_path / "targets.db"
    monkeypatch.setattr(
        "snarkyctl.cli.migrate_yaml_catalogue",
        lambda _config, _database: MigrationResult(
            provider="nordvpn",
            database=database,
            revision=1,
            migrated_count=2,
            yaml_backup=tmp_path / "targets.yaml.pre-sqlite",
            database_backup=None,
        ),
    )
    assert (
        main(
            [
                "targets-db",
                "migrate",
                "--config",
                str(tmp_path / "snarkyctl.yaml"),
                "--database",
                str(database),
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "Migrated 2 targets" in output
    assert "YAML remains authoritative" in output


def test_targets_export_and_replace_round_trip(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ordinary = ControlResponse(
        request_id="0de2718e-98b1-43a0-879f-867d87b81a75",
        success=True,
        message="ok",
        target_catalog=VpnTargetCatalog(
            provider="nordvpn",
            capabilities=ProviderCapabilities(
                connect=True,
                disconnect=True,
                target_selection=True,
                server_details=True,
            ),
            targets=(VpnTargetSummary(alias="dallas", label="Dallas"),),
        ),
    )
    catalogue = TargetCatalogue(
        provider="nordvpn",
        revision=2,
        targets=(
            StoredTarget(
                alias="dallas",
                label="Dallas",
                position=0,
                selector={"kind": "recommended"},
            ),
        ),
    )
    monkeypatch.setattr("snarkyctl.cli.ControlClient.targets", lambda _self: ordinary)
    monkeypatch.setattr(
        "snarkyctl.cli.ControlClient.editable_catalogue",
        lambda *_args: ControlResponse(
            request_id="0de2718e-98b1-43a0-879f-867d87b81a75",
            success=True,
            message="ok",
            editable_target_catalogue=catalogue,
        ),
    )
    assert main(["targets", "export"]) == 0
    exported = capsys.readouterr().out
    assert '"expected_revision": 2' in exported
    replacement = tmp_path / "replacement.json"
    replacement.write_text(exported, encoding="utf-8")
    monkeypatch.setattr(
        "snarkyctl.cli.ControlClient.replace_catalogue",
        lambda *_args: ControlResponse(
            request_id="0de2718e-98b1-43a0-879f-867d87b81a75",
            success=True,
            message="ok",
            editable_target_catalogue=catalogue.model_copy(update={"revision": 3}),
        ),
    )
    assert main(["targets", "replace", str(replacement)]) == 0
    assert "revision=3" in capsys.readouterr().out


def test_targets_list_and_schema(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ordinary = ControlResponse(
        request_id="0de2718e-98b1-43a0-879f-867d87b81a75",
        success=True,
        message="ok",
        target_catalog=VpnTargetCatalog(
            provider="nordvpn",
            capabilities=ProviderCapabilities(
                connect=True,
                disconnect=True,
                target_selection=True,
                server_details=True,
            ),
            targets=(VpnTargetSummary(alias="dallas", label="Dallas"),),
        ),
    )
    schema = ProviderTargetSchema(
        provider="nordvpn",
        selector_kinds=(SelectorKind(kind="recommended", label="Recommended"),),
    )
    monkeypatch.setattr("snarkyctl.cli.ControlClient.targets", lambda _self: ordinary)
    monkeypatch.setattr(
        "snarkyctl.cli.ControlClient.target_schema",
        lambda *_args: ControlResponse(
            request_id="0de2718e-98b1-43a0-879f-867d87b81a75",
            success=True,
            message="ok",
            provider_target_schema=schema,
        ),
    )
    assert main(["targets", "list"]) == 0
    assert "dallas\tDallas" in capsys.readouterr().out
    assert main(["targets", "list", "--json"]) == 0
    assert '"provider": "nordvpn"' in capsys.readouterr().out
    assert main(["targets", "schema"]) == 0
    assert '"recommended"' in capsys.readouterr().out


def test_targets_replace_rejects_invalid_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "snarkyctl.cli.ControlClient.targets",
        lambda _self: ControlResponse(
            request_id="0de2718e-98b1-43a0-879f-867d87b81a75",
            success=True,
            message="ok",
            target_catalog=VpnTargetCatalog(
                provider="nordvpn",
                capabilities=ProviderCapabilities(
                    connect=True,
                    disconnect=True,
                    target_selection=True,
                    server_details=True,
                ),
                targets=(),
            ),
        ),
    )
    invalid = tmp_path / "invalid.json"
    invalid.write_text("not json", encoding="utf-8")
    assert main(["targets", "replace", str(invalid)]) == 2
    assert "INVALID_CATALOG" in capsys.readouterr().err


@pytest.mark.parametrize("subcommand", ["list", "schema", "export"])
def test_targets_reports_catalogue_lookup_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    subcommand: str,
) -> None:
    monkeypatch.setattr(
        "snarkyctl.cli.ControlClient.targets",
        lambda _self: ControlResponse(
            request_id="0de2718e-98b1-43a0-879f-867d87b81a75",
            success=False,
            error_code="CATALOG_STORAGE_FAILED",
            message="catalogue unavailable",
        ),
    )

    assert main(["targets", subcommand]) == 1
    assert "CATALOG_STORAGE_FAILED: catalogue unavailable" in capsys.readouterr().err


def test_targets_reports_control_transport_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(_self: object) -> ControlResponse:
        raise ControlClientError("CONTROL_UNAVAILABLE", "socket unavailable")

    monkeypatch.setattr("snarkyctl.cli.ControlClient.targets", fail)

    assert main(["targets", "list"]) == 2
    assert "CONTROL_UNAVAILABLE: socket unavailable" in capsys.readouterr().err

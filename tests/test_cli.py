"""Tests for the SnarkyCtl command-line entry point."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from snarkyctl import __version__
from snarkyctl.cli import main
from snarkyctl.control.client import ControlClientError
from snarkyctl.control.protocol import ControlResponse
from snarkyctl.preflight import CheckResult, CheckStatus, PreflightReport
from snarkyctl.providers.base import GatewayMode, VpnState, VpnStatus
from snarkyctl.status import ComponentFailure, DnsStatus, GatewayStatus, SystemStatus


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

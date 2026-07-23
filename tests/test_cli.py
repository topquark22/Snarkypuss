"""Tests for the SnarkyCtl command-line entry point."""

from pathlib import Path

import pytest

from snarkyctl import __version__
from snarkyctl.cli import main
from snarkyctl.preflight import CheckResult, CheckStatus, PreflightReport


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

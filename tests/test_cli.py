"""Tests for the SnarkyCtl command-line entry point."""

from pathlib import Path

import pytest

from snarkyctl import __version__
from snarkyctl.cli import main


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

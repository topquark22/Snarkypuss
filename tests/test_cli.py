"""Tests for the SnarkyCtl command-line entry point."""

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

"""Tests for the read-only Snarkypuss gateway helper scripts."""

import re
import subprocess
from pathlib import Path

import pytest


SCRIPT_PATHS = (
    Path("scripts/snarkypuss-preflight.sh"),
    Path("scripts/snarkypuss-verify.sh"),
)


@pytest.mark.parametrize("script_path", SCRIPT_PATHS)
def test_gateway_script_has_valid_posix_shell_syntax(script_path: Path) -> None:
    subprocess.run(
        ["sh", "-n", str(script_path)],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("script_path", SCRIPT_PATHS)
def test_gateway_script_help_is_successful_and_read_only(script_path: Path) -> None:
    result = subprocess.run(
        ["sh", str(script_path), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "read-only" in result.stdout.lower()
    assert "Exit status:" in result.stdout


def test_gateway_preflight_rejects_invalid_port() -> None:
    result = subprocess.run(
        ["sh", str(SCRIPT_PATHS[0]), "--listen-port", "invalid"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "Invalid UDP listen port" in result.stderr


def test_gateway_verifier_requires_https_for_public_ip_lookup() -> None:
    result = subprocess.run(
        ["sh", str(SCRIPT_PATHS[1]), "--public-ip-url", "http://example.com"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "must use HTTPS" in result.stderr


@pytest.mark.parametrize("script_path", SCRIPT_PATHS)
def test_increment_one_gateway_scripts_contain_no_mutating_commands(
    script_path: Path,
) -> None:
    script = script_path.read_text(encoding="utf-8")
    forbidden_command = re.compile(
        r"^\s*(?:"
        r"apt(?:-get)?\s+install|"
        r"systemctl\s+(?:enable|start|stop|restart)|"
        r"iptables\s+-(?:A|D|F|I|R|X)|"
        r"ip\s+route\s+(?:add|delete|replace)|"
        r"sysctl\s+-w|"
        r"sed\s+-i|"
        r"rm\s|"
        r"mv\s|"
        r"cp\s"
        r")",
        flags=re.MULTILINE,
    )

    assert forbidden_command.search(script) is None

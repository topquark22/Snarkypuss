"""Tests for the read-only Snarkypuss gateway helper scripts."""

import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT_PATHS = (
    Path("scripts/snarkypuss-preflight.sh"),
    Path("scripts/snarkypuss-verify.sh"),
)
INSTALL_SCRIPT = Path("scripts/snarkypuss-install.sh")
CONFIGURE_SCRIPT = Path("scripts/snarkypuss-configure.py")
PRIVATE_KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
PUBLIC_KEY = "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE="


@pytest.mark.parametrize("script_path", SCRIPT_PATHS)
def test_gateway_script_has_valid_posix_shell_syntax(script_path: Path) -> None:
    subprocess.run(  # noqa: S603, S607 - repository script under test
        ["sh", "-n", str(script_path)],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("script_path", SCRIPT_PATHS)
def test_gateway_script_help_is_successful_and_read_only(script_path: Path) -> None:
    result = subprocess.run(  # noqa: S603, S607 - repository script under test
        ["sh", str(script_path), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "read-only" in result.stdout.lower()
    assert "Exit status:" in result.stdout


def test_gateway_preflight_rejects_invalid_port() -> None:
    result = subprocess.run(  # noqa: S603, S607 - repository script under test
        ["sh", str(SCRIPT_PATHS[0]), "--listen-port", "invalid"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "Invalid UDP listen port" in result.stderr


def test_gateway_verifier_requires_https_for_public_ip_lookup() -> None:
    result = subprocess.run(  # noqa: S603, S607 - repository script under test
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


def test_gateway_installer_dry_run_prints_fixed_package_plan() -> None:
    result = subprocess.run(  # noqa: S603, S607 - repository script under test
        [
            "sh",
            str(INSTALL_SCRIPT),
            "--dry-run",
            "--skip-update",
            "--allow-unsupported",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "apt-get install --yes" in result.stdout
    assert "wireguard-tools" in result.stdout
    assert "dnsmasq" in result.stdout
    assert "No packages were installed" in result.stdout


def test_gateway_installer_does_not_activate_networking() -> None:
    script = INSTALL_SCRIPT.read_text(encoding="utf-8")

    assert "systemctl start" not in script
    assert "systemctl enable" not in script
    assert "systemctl disable --now dnsmasq.service" in script
    assert "iptables -A" not in script
    assert "ip route add" not in script
    assert "nordvpn connect" not in script.lower()


def write_setup_file(directory: Path, *, dns: str = "1.1.1.1, 1.0.0.1") -> Path:
    client_key = directory / "client.pub"
    client_key.write_text(f"{PUBLIC_KEY}\n", encoding="ascii")
    setup = directory / "setup.conf"
    setup.write_text(
        "\n".join(
            (
                "[gateway]",
                "tunnel_interface = wg0",
                "server_address = 10.8.0.1/24",
                "listen_port = 51820",
                "client_address = 10.8.0.2/32",
                f"client_public_key_file = {client_key}",
                f"dns_upstreams = {dns}",
                "",
            )
        ),
        encoding="utf-8",
    )
    return setup


def test_gateway_configuration_dry_run_writes_nothing(tmp_path: Path) -> None:
    setup = write_setup_file(tmp_path)
    destination = tmp_path / "root"

    result = subprocess.run(  # noqa: S603 - fixed interpreter and repository script
        [
            sys.executable,
            str(CONFIGURE_SCRIPT),
            "--config",
            str(setup),
            "--root",
            str(destination),
            "--dry-run",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "Mode: dry-run" in result.stdout
    assert "No files were written" in result.stdout
    assert not destination.exists()


def test_gateway_configuration_apply_is_idempotent_and_private(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup = write_setup_file(tmp_path)
    destination = tmp_path / "root"
    binary_directory = tmp_path / "bin"
    binary_directory.mkdir()
    fake_wg = binary_directory / "wg"
    fake_wg.write_text(
        "\n".join(
            (
                "#!/bin/sh",
                'case "$1" in',
                f"  genkey) printf '%s\\n' '{PRIVATE_KEY}' ;;",
                f"  pubkey) cat >/dev/null; printf '%s\\n' '{PUBLIC_KEY}' ;;",
                "  *) exit 2 ;;",
                "esac",
                "",
            )
        ),
        encoding="utf-8",
    )
    fake_wg.chmod(0o755)
    monkeypatch.setenv("PATH", f"{binary_directory}:{os.environ['PATH']}")

    command = [
        sys.executable,
        str(CONFIGURE_SCRIPT),
        "--config",
        str(setup),
        "--root",
        str(destination),
        "--apply",
    ]
    first = subprocess.run(  # noqa: S603 - fixed interpreter and repository script
        command, check=True, capture_output=True, text=True
    )
    second = subprocess.run(  # noqa: S603 - fixed interpreter and repository script
        command, check=True, capture_output=True, text=True
    )

    wireguard_directory = destination / "etc/wireguard"
    private_key = wireguard_directory / "wg0.private.key"
    wireguard_config = wireguard_directory / "wg0.conf"
    dns_config = destination / "etc/dnsmasq.d/snarkypuss.conf"
    sysctl_config = destination / "etc/sysctl.d/90-snarkypuss.conf"

    assert "Server WireGuard public key" in first.stdout
    assert "UNCHANGED" in second.stdout
    assert private_key.read_text(encoding="ascii").strip() == PRIVATE_KEY
    assert f"PrivateKey = {PRIVATE_KEY}" in wireguard_config.read_text(encoding="utf-8")
    assert "PublicKey = " + PUBLIC_KEY in wireguard_config.read_text(encoding="utf-8")
    assert "PostUp" not in wireguard_config.read_text(encoding="utf-8")
    assert "PostDown" not in wireguard_config.read_text(encoding="utf-8")
    assert "server=1.1.1.1" in dns_config.read_text(encoding="utf-8")
    assert "net.ipv4.ip_forward=1" in sysctl_config.read_text(encoding="utf-8")
    assert stat.S_IMODE(private_key.stat().st_mode) == 0o600
    assert stat.S_IMODE(wireguard_config.stat().st_mode) == 0o600
    assert stat.S_IMODE(wireguard_directory.stat().st_mode) == 0o700
    assert list(destination.rglob("*.bak.*")) == []

    write_setup_file(tmp_path, dns="9.9.9.9, 149.112.112.112")
    third = subprocess.run(  # noqa: S603 - fixed interpreter and repository script
        command, check=True, capture_output=True, text=True
    )
    dns_backups = list(dns_config.parent.glob("snarkypuss.conf.bak.*"))
    assert "BACKUP" in third.stdout
    assert len(dns_backups) == 1
    assert "server=1.1.1.1" in dns_backups[0].read_text(encoding="utf-8")
    assert "server=9.9.9.9" in dns_config.read_text(encoding="utf-8")


def test_gateway_configuration_rejects_unknown_options(tmp_path: Path) -> None:
    setup = write_setup_file(tmp_path)
    setup.write_text(
        setup.read_text(encoding="utf-8") + "provider_command = arbitrary\n",
        encoding="utf-8",
    )

    result = subprocess.run(  # noqa: S603, S607 - repository script under test
        [
            sys.executable,
            str(CONFIGURE_SCRIPT),
            "--config",
            str(setup),
            "--root",
            str(tmp_path / "root"),
            "--dry-run",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "unknown setup option" in result.stderr

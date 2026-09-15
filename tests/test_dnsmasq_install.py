"""Regression checks for dnsmasq preparation in the base gateway installer."""

import subprocess
from pathlib import Path


INSTALL_SCRIPT = Path("scripts/snarkypuss-install.sh")


def test_install_dry_run_describes_dnsmasq_binding_fix() -> None:
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

    assert "bind-interfaces" in result.stdout
    assert "bind-dynamic" in result.stdout
    assert "No packages were installed" in result.stdout


def test_installer_only_rewrites_dnsmasq_config_after_new_install() -> None:
    script = INSTALL_SCRIPT.read_text(encoding="utf-8")

    assert (
        'if [ "$dnsmasq_preexisting" != true ] && [ -f /etc/dnsmasq.conf ]; then'
        in script
    )
    assert "dnsmasq.conf.snarkypuss-original" in script
    assert "cp -a /etc/dnsmasq.conf" in script
    assert "bind-interfaces" in script
    assert "bind-dynamic" in script
    assert "administrator-owned and is left untouched" in script

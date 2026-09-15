"""Regression checks for dedicated dnsmasq ownership in the base gateway installer."""

import subprocess
from pathlib import Path


INSTALL_SCRIPT = Path("scripts/snarkypuss-install.sh")


def test_install_dry_run_uses_dnsmasq_base_only() -> None:
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

    assert "dnsmasq-base" in result.stdout
    assert "dedicated snarkypuss-dns.service" in result.stdout
    assert "stock dnsmasq service/configuration is not installed or modified" in result.stdout
    assert "No packages were installed" in result.stdout


def test_installer_does_not_modify_stock_dnsmasq_configuration() -> None:
    script = INSTALL_SCRIPT.read_text(encoding="utf-8")

    assert "dnsmasq-base" in script
    assert "/etc/dnsmasq.conf" not in script
    assert "bind-interfaces" not in script
    assert "dnsmasq.conf.snarkypuss-original" not in script
    assert "systemctl disable --now dnsmasq.service" not in script
    assert "dpkg-query" not in script

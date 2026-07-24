"""Tests for package metadata and the minimal HTTP application."""

import asyncio
import re
import tomllib
from pathlib import Path

import httpx

from snarkyctl import __version__
from snarkyctl.main import app


def test_package_has_development_version() -> None:
    assert __version__ == "0.1.0.dev4"


def test_debian_version_matches_python_development_version() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    python_version = project["project"]["version"]
    changelog_first_line = Path("debian/changelog").read_text(encoding="utf-8").splitlines()[0]
    match = re.fullmatch(r"snarkyctl \(([^)]+)\) unstable; urgency=medium", changelog_first_line)

    assert match is not None
    debian_version = match.group(1)
    upstream_version, revision = debian_version.rsplit("-", maxsplit=1)
    assert upstream_version == python_version.replace(".dev", "~dev")
    assert revision.isdecimal()
    assert int(revision) >= 1


def test_debian_package_installs_all_systemd_units_inactive() -> None:
    install_manifest = Path("debian/snarkyctl.install").read_text(encoding="utf-8")
    rules = Path("debian/rules").read_text(encoding="utf-8")

    for unit_name in (
        "snarkyctl-control.socket",
        "snarkyctl-control.service",
        "snarkyctl-web.service",
    ):
        assert f"systemd/{unit_name} usr/lib/systemd/system/" in install_manifest
    assert "dh_installsystemd --no-enable --no-start" in rules


def test_builtin_venv_does_not_receive_virtualenv_only_options() -> None:
    rules = Path("debian/rules").read_text(encoding="utf-8")

    assert "--builtin-venv" in rules
    assert "--setuptools" not in rules
    assert "DH_VERBOSE" not in rules


def test_debian_postinst_has_no_network_or_service_activation() -> None:
    postinst = Path("debian/postinst").read_text(encoding="utf-8")

    for forbidden_command in ("apt-get", "curl", "pip install", "systemctl enable", "systemctl start"):
        assert forbidden_command not in postinst


def test_reinstall_script_is_guarded_and_restarts_all_units() -> None:
    script = Path("scripts/reinstall-deb.sh").read_text(encoding="utf-8")

    assert "set -eu" in script
    assert 'if [ "$(id -u)" -ne 0 ]' in script
    assert 'if [ "$package_name" != "snarkyctl" ]' in script
    assert 'apt-get install --yes --reinstall "$package_path"' in script

    for unit_name in (
        "snarkyctl-web.service",
        "snarkyctl-control.service",
        "snarkyctl-control.socket",
    ):
        assert f"systemctl stop {unit_name}" in script
        assert f"systemctl start {unit_name}" in script
        assert f"systemctl is-active --quiet {unit_name}" in script


def test_liveness_endpoint() -> None:
    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="https://test") as client:
            return await client.get("/api/health/live")

    response = asyncio.run(request())

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "snarkyctl-web",
        "version": __version__,
    }

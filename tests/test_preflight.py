"""Tests for read-only deployment preflight checks."""

from __future__ import annotations

import json
import socket
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from snarkyctl.config import LoadedConfig
from snarkyctl.preflight import (
    CheckResult,
    CheckStatus,
    PreflightReport,
    _auth_check,
    _file_security,
    _identity_checks,
    _interface_checks,
    _port_check,
    _provider_checks,
    _socket_check,
    _systemd_checks,
    _tls_checks,
    format_report,
    run_preflight,
)


def make_config(tmp_path: Path) -> LoadedConfig:
    return LoadedConfig.model_validate(
        {
            "settings": {
                "schema_version": 1,
                "network": {
                    "management_interface": "wg0",
                    "management_address": "10.8.0.1/24",
                    "client_subnet": "10.8.0.0/24",
                    "public_interface": "eth0",
                },
                "web": {
                    "bind_address": "10.8.0.1",
                    "port": 8443,
                    "auth_file": str(tmp_path / "auth.htpasswd"),
                    "tls_certificate": str(tmp_path / "server.crt"),
                    "tls_private_key": str(tmp_path / "server.key"),
                    "request_timeout_seconds": 10,
                },
                "control": {
                    "socket_path": str(tmp_path / "control.sock"),
                    "operation_timeout_seconds": 60,
                },
                "upstream_vpn": {
                    "provider": "nordvpn",
                    "expected_interfaces": ["nordlynx"],
                    "targets_file": str(tmp_path / "targets.yaml"),
                },
            },
            "targets": {
                "schema_version": 1,
                "targets": [{"alias": "dallas", "label": "Dallas", "provider_target": "us"}],
            },
        }
    )


def test_report_output_and_passed_property() -> None:
    report = PreflightReport(
        checks=(
            CheckResult(check_id="one", status=CheckStatus.PASS, message="good"),
            CheckResult(check_id="two", status=CheckStatus.WARN, message="notice"),
        )
    )
    assert report.passed
    assert "PASS  one: good" in format_report(report)
    assert json.loads(report.as_json())["schema_version"] == 1
    failed = PreflightReport(
        checks=(CheckResult(check_id="bad", status=CheckStatus.FAIL, message="bad"),)
    )
    assert not failed.passed


def test_file_security_accepts_safe_file_and_rejects_unsafe_mode(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("data", encoding="utf-8")
    path.chmod(0o600)
    assert _file_security("file", path).status is CheckStatus.PASS
    path.chmod(0o606)
    result = _file_security("file", path)
    assert result.status is CheckStatus.FAIL
    assert "unsafe mode" in result.message


def test_file_security_rejects_missing_and_symlink(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    assert _file_security("file", missing).status is CheckStatus.FAIL
    target = tmp_path / "target"
    target.write_text("x", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(target)
    assert _file_security("file", link).status is CheckStatus.FAIL


def test_identity_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "snarkyctl.preflight.pwd.getpwnam",
        lambda _name: SimpleNamespace(pw_shell="/usr/sbin/nologin", pw_gid=123),
    )
    monkeypatch.setattr(
        "snarkyctl.preflight.grp.getgrnam", lambda _name: SimpleNamespace(gr_gid=123)
    )
    assert all(result.status is CheckStatus.PASS for result in _identity_checks())


def test_identity_checks_missing_user(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(_name: str) -> None:
        raise KeyError

    monkeypatch.setattr("snarkyctl.preflight.pwd.getpwnam", missing)
    assert _identity_checks()[0].status is CheckStatus.FAIL


def test_identity_checks_reject_interactive_shell_and_wrong_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "snarkyctl.preflight.pwd.getpwnam",
        lambda _name: SimpleNamespace(pw_shell="/bin/bash", pw_gid=111),
    )
    monkeypatch.setattr(
        "snarkyctl.preflight.grp.getgrnam", lambda _name: SimpleNamespace(gr_gid=222)
    )
    results = _identity_checks()
    assert results[1].status is CheckStatus.FAIL
    assert results[2].status is CheckStatus.FAIL


def test_auth_file_requires_bcrypt_record(tmp_path: Path) -> None:
    auth = tmp_path / "auth"
    auth.write_text(
        "admin:$2b$12$abcdefghijklmnopqrstuvwxyz012345678901234567890\n",
        encoding="utf-8",
    )
    assert _auth_check(auth).status is CheckStatus.PASS
    auth.write_text("admin:plaintext\n", encoding="utf-8")
    assert _auth_check(auth).status is CheckStatus.FAIL


def test_provider_prerequisite(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = make_config(tmp_path)
    executable = tmp_path / "nordvpn"
    executable.write_text("", encoding="utf-8")
    executable.chmod(0o755)
    monkeypatch.setattr("snarkyctl.preflight.NORDVPN_EXECUTABLE", executable)
    assert _provider_checks(config)[0].status is CheckStatus.PASS
    executable.chmod(0o644)
    assert _provider_checks(config)[0].status is CheckStatus.FAIL


def test_interface_checks_report_missing_interfaces(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = make_config(tmp_path)

    def missing(_name: str) -> int:
        raise OSError("missing")

    monkeypatch.setattr("snarkyctl.preflight.socket.if_nametoindex", missing)
    results = _interface_checks(config)
    assert results[0].status is CheckStatus.FAIL
    assert results[1].status is CheckStatus.FAIL
    assert results[2].status is CheckStatus.FAIL


def test_port_check_detects_available_and_occupied_port(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    web = config.settings.web.model_copy(update={"bind_address": "127.0.0.1", "port": 0})
    settings = config.settings.model_copy(update={"web": web})
    local = config.model_copy(update={"settings": settings})
    assert _port_check(local).status is CheckStatus.PASS

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    try:
        occupied_web = web.model_copy(update={"port": listener.getsockname()[1]})
        occupied = local.model_copy(
            update={"settings": settings.model_copy(update={"web": occupied_web})}
        )
        assert _port_check(occupied).status is CheckStatus.FAIL
    finally:
        listener.close()


def test_systemd_source_checks(tmp_path: Path) -> None:
    (tmp_path / "snarkyctl-web.service").write_text(
        "User=snarkyctl\nGroup=snarkyctl\nNoNewPrivileges=true\n", encoding="utf-8"
    )
    (tmp_path / "snarkyctl-control.service").write_text(
        "User=root\nGroup=root\nNoNewPrivileges=true\n", encoding="utf-8"
    )
    (tmp_path / "snarkyctl-control.socket").write_text(
        "ListenStream=/run/snarkyctl/control.sock\nSocketUser=root\nSocketGroup=snarkyctl\nSocketMode=0660\n",
        encoding="utf-8",
    )
    assert all(result.status is CheckStatus.PASS for result in _systemd_checks(tmp_path))
    (tmp_path / "snarkyctl-web.service").write_text("User=root\n", encoding="utf-8")
    assert _systemd_checks(tmp_path)[0].status is CheckStatus.FAIL


def test_inactive_control_socket_is_skipped(tmp_path: Path) -> None:
    result = _socket_check(tmp_path / "control.sock", 123)
    assert result.status is CheckStatus.SKIP


def test_live_control_socket_permissions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "control.sock"
    safe = SimpleNamespace(st_mode=stat.S_IFSOCK | 0o660, st_uid=0, st_gid=123)
    monkeypatch.setattr(Path, "lstat", lambda _path: safe)
    assert _socket_check(path, 123).status is CheckStatus.PASS
    unsafe = SimpleNamespace(st_mode=stat.S_IFSOCK | 0o666, st_uid=0, st_gid=123)
    monkeypatch.setattr(Path, "lstat", lambda _path: unsafe)
    assert _socket_check(path, 123).status is CheckStatus.FAIL


def test_tls_checks_match_key_validity_and_ip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = make_config(tmp_path)

    class FakeContext:
        def load_cert_chain(self, _cert: Path, _key: Path) -> None:
            return None

    monkeypatch.setattr("snarkyctl.preflight.ssl.SSLContext", lambda _protocol: FakeContext())
    monkeypatch.setattr(
        "snarkyctl.preflight._certificate_details",
        lambda _path: {
            "notAfter": "Jan  1 00:00:00 2099 GMT",
            "subjectAltName": (("IP Address", "10.8.0.1"),),
        },
    )
    assert all(result.status is CheckStatus.PASS for result in _tls_checks(config))


def test_tls_checks_reject_bad_key_pair(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = make_config(tmp_path)

    class BadContext:
        def load_cert_chain(self, _cert: Path, _key: Path) -> None:
            raise OSError("bad pair")

    monkeypatch.setattr("snarkyctl.preflight.ssl.SSLContext", lambda _protocol: BadContext())
    result = _tls_checks(config)[0]
    assert result.status is CheckStatus.FAIL


def test_run_preflight_aggregates_and_marks_firewall_skip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = make_config(tmp_path)
    monkeypatch.setattr("snarkyctl.preflight.load_config", lambda _path: config)
    monkeypatch.setattr("snarkyctl.preflight._identity_checks", lambda: [])
    monkeypatch.setattr(
        "snarkyctl.preflight._file_security",
        lambda check_id, _path, **_kwargs: CheckResult(
            check_id=check_id, status=CheckStatus.PASS, message="safe"
        ),
    )
    monkeypatch.setattr("snarkyctl.preflight._interface_checks", lambda _config: [])
    monkeypatch.setattr(
        "snarkyctl.preflight._port_check",
        lambda _config: CheckResult(check_id="port", status=CheckStatus.PASS, message="free"),
    )
    monkeypatch.setattr(
        "snarkyctl.preflight._auth_check",
        lambda _path: CheckResult(check_id="auth", status=CheckStatus.PASS, message="valid"),
    )
    monkeypatch.setattr("snarkyctl.preflight._tls_checks", lambda _config: [])
    monkeypatch.setattr("snarkyctl.preflight._provider_checks", lambda _config: [])
    monkeypatch.setattr("snarkyctl.preflight._systemd_checks", lambda _path: [])
    monkeypatch.setattr(
        "snarkyctl.preflight._socket_check",
        lambda _path, _gid: CheckResult(
            check_id="socket", status=CheckStatus.SKIP, message="inactive"
        ),
    )
    monkeypatch.setattr(
        "snarkyctl.preflight.grp.getgrnam", lambda _name: SimpleNamespace(gr_gid=123)
    )
    report = run_preflight(tmp_path / "snarkyctl.yaml", unit_dir=tmp_path)
    assert report.passed
    assert report.checks[-1].check_id == "firewall.policy"
    assert report.checks[-1].status is CheckStatus.SKIP

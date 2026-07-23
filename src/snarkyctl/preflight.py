"""Read-only deployment checks run before SnarkyCtl service activation."""

from __future__ import annotations

import grp
import json
import os
import pwd
import socket
import ssl
import stat
import struct
from collections.abc import Iterable
from datetime import UTC, datetime
from enum import StrEnum
from fcntl import ioctl
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from snarkyctl.config import LoadedConfig, load_config
from snarkyctl.providers.nordvpn import NORDVPN_EXECUTABLE

SYSTEM_USER = "snarkyctl"
SYSTEM_GROUP = "snarkyctl"
SYSTEMD_UNIT_DIR = Path("/usr/lib/systemd/system")


class CheckStatus(StrEnum):
    """Stable result states for humans and automation."""

    PASS = "PASS"  # noqa: S105 - status label, not a credential
    WARN = "WARN"
    FAIL = "FAIL"
    SKIP = "SKIP"


class CheckResult(BaseModel):
    """One stable, machine-readable preflight result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    check_id: str
    status: CheckStatus
    message: str


class PreflightReport(BaseModel):
    """Complete preflight result document."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    checks: tuple[CheckResult, ...]

    @property
    def passed(self) -> bool:
        return not any(check.status is CheckStatus.FAIL for check in self.checks)

    def as_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), indent=2, sort_keys=True)


def _result(check_id: str, status: CheckStatus, message: str) -> CheckResult:
    return CheckResult(check_id=check_id, status=status, message=message)


def _file_security(
    check_id: str,
    path: Path,
    *,
    expected_uid: int = 0,
    expected_gid: int | None = None,
    allow_group_read: bool = True,
    allow_other_read: bool = False,
) -> CheckResult:
    try:
        metadata = path.lstat()
    except OSError as exc:
        return _result(check_id, CheckStatus.FAIL, f"cannot inspect {path}: {exc.strerror}")
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        return _result(check_id, CheckStatus.FAIL, f"{path} must be a regular non-symlink file")
    if metadata.st_uid != expected_uid:
        return _result(check_id, CheckStatus.FAIL, f"{path} is not owned by uid {expected_uid}")
    if expected_gid is not None and metadata.st_gid != expected_gid:
        return _result(check_id, CheckStatus.FAIL, f"{path} has the wrong group")
    permissions = stat.S_IMODE(metadata.st_mode)
    forbidden = stat.S_IWGRP | stat.S_IWOTH
    if not allow_group_read:
        forbidden |= stat.S_IRGRP
    if not allow_other_read:
        forbidden |= stat.S_IROTH
    if permissions & forbidden:
        return _result(check_id, CheckStatus.FAIL, f"{path} has unsafe mode {permissions:04o}")
    return _result(check_id, CheckStatus.PASS, f"{path} ownership and mode are safe")


def _identity_checks() -> list[CheckResult]:
    results: list[CheckResult] = []
    try:
        account = pwd.getpwnam(SYSTEM_USER)
    except KeyError:
        return [_result("identity.user", CheckStatus.FAIL, f"user {SYSTEM_USER} does not exist")]
    results.append(_result("identity.user", CheckStatus.PASS, f"user {SYSTEM_USER} exists"))
    if account.pw_shell.endswith(("/nologin", "/false")):
        results.append(
            _result("identity.login_shell", CheckStatus.PASS, "service account cannot log in")
        )
    else:
        results.append(
            _result(
                "identity.login_shell",
                CheckStatus.FAIL,
                f"service account has interactive shell {account.pw_shell}",
            )
        )
    try:
        group = grp.getgrnam(SYSTEM_GROUP)
    except KeyError:
        results.append(
            _result("identity.group", CheckStatus.FAIL, f"group {SYSTEM_GROUP} does not exist")
        )
    else:
        status = CheckStatus.PASS if account.pw_gid == group.gr_gid else CheckStatus.FAIL
        message = "service account primary group is correct" if status is CheckStatus.PASS else (
            "service account primary group is not snarkyctl"
        )
        results.append(_result("identity.group", status, message))
    return results


def _interface_checks(config: LoadedConfig) -> list[CheckResult]:
    network = config.settings.network
    results: list[CheckResult] = []
    for check_id, interface in (
        ("network.management_interface", network.management_interface),
        ("network.public_interface", network.public_interface),
    ):
        try:
            socket.if_nametoindex(interface)
        except OSError:
            results.append(
                _result(check_id, CheckStatus.FAIL, f"interface {interface} does not exist")
            )
        else:
            results.append(_result(check_id, CheckStatus.PASS, f"interface {interface} exists"))

    address = str(network.management_address.ip)
    try:
        request = struct.pack("256s", network.management_interface.encode("ascii")[:15])
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            response = ioctl(probe.fileno(), 0x8915, request)
        assigned_address = socket.inet_ntoa(response[20:24])
    except OSError as exc:
        results.append(
            _result(
                "network.management_address",
                CheckStatus.FAIL,
                f"cannot inspect address on {network.management_interface}: {exc}",
            )
        )
    else:
        status = CheckStatus.PASS if address == assigned_address else CheckStatus.FAIL
        message = f"management address {address} is present" if status is CheckStatus.PASS else (
            f"management address {address} is not assigned"
        )
        results.append(_result("network.management_address", status, message))
    return results


def _port_check(config: LoadedConfig) -> CheckResult:
    web = config.settings.web
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((str(web.bind_address), web.port))
    except OSError as exc:
        return _result(
            "network.web_port",
            CheckStatus.FAIL,
            f"cannot reserve {web.bind_address}:{web.port}: {exc.strerror}",
        )
    finally:
        probe.close()
    return _result(
        "network.web_port",
        CheckStatus.PASS,
        f"{web.bind_address}:{web.port} is available",
    )


def _auth_check(path: Path) -> CheckResult:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        return _result("auth.syntax", CheckStatus.FAIL, f"cannot read {path}: {exc}")
    records = [line for line in lines if line and not line.startswith("#")]
    valid = all(
        ":" in line
        and bool(line.split(":", 1)[0])
        and line.split(":", 1)[1].startswith(("$2a$", "$2b$", "$2y$"))
        for line in records
    )
    if not records or not valid:
        return _result(
            "auth.syntax", CheckStatus.FAIL, "auth file needs at least one valid bcrypt record"
        )
    return _result("auth.syntax", CheckStatus.PASS, f"auth file contains {len(records)} record(s)")


def _certificate_details(path: Path) -> dict[str, Any]:
    # CPython exposes this decoder for its own TLS test and inspection tooling.
    return ssl._ssl._test_decode_cert(str(path))  # type: ignore[attr-defined,no-any-return]


def _tls_checks(config: LoadedConfig) -> list[CheckResult]:
    web = config.settings.web
    try:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(web.tls_certificate, web.tls_private_key)
    except (OSError, ssl.SSLError) as exc:
        return [_result("tls.key_pair", CheckStatus.FAIL, f"certificate/key load failed: {exc}")]
    results = [_result("tls.key_pair", CheckStatus.PASS, "certificate and private key match")]
    try:
        details = _certificate_details(web.tls_certificate)
        not_after = details.get("notAfter")
        if not isinstance(not_after, str):
            raise ValueError("certificate does not contain a valid notAfter field")
        expires = datetime.fromtimestamp(ssl.cert_time_to_seconds(not_after), tz=UTC)
    except (OSError, ssl.SSLError, TypeError, ValueError) as exc:
        results.append(_result("tls.validity", CheckStatus.FAIL, f"cannot read validity: {exc}"))
        return results
    now = datetime.now(UTC)
    status = CheckStatus.PASS if expires > now else CheckStatus.FAIL
    results.append(_result("tls.validity", status, f"certificate expires {expires.isoformat()}"))
    expected_ip = str(web.bind_address)
    sans = details.get("subjectAltName", ())
    covered = any(kind == "IP Address" and value == expected_ip for kind, value in sans)
    results.append(
        _result(
            "tls.management_address",
            CheckStatus.PASS if covered else CheckStatus.FAIL,
            f"certificate {'covers' if covered else 'does not cover'} {expected_ip}",
        )
    )
    return results


def _provider_checks(config: LoadedConfig) -> list[CheckResult]:
    provider = config.settings.upstream_vpn.provider
    if provider != "nordvpn":
        return [
            _result(
                "provider.prerequisites",
                CheckStatus.SKIP,
                f"provider {provider} has no preflight implementation",
            )
        ]
    executable = NORDVPN_EXECUTABLE
    if not executable.is_file() or not os.access(executable, os.X_OK):
        return [
            _result(
                "provider.executable",
                CheckStatus.FAIL,
                f"NordVPN executable is not runnable at {executable}",
            )
        ]
    return [
        _result(
            "provider.executable", CheckStatus.PASS, f"NordVPN executable found at {executable}"
        )
    ]


def _unit_check(path: Path, required: Iterable[str], check_id: str) -> CheckResult:
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return _result(check_id, CheckStatus.FAIL, f"cannot read {path}: {exc}")
    missing = [directive for directive in required if directive not in content]
    if missing:
        return _result(check_id, CheckStatus.FAIL, f"missing directives: {', '.join(missing)}")
    return _result(check_id, CheckStatus.PASS, f"{path.name} has required security directives")


def _systemd_checks(unit_dir: Path) -> list[CheckResult]:
    return [
        _unit_check(
            unit_dir / "snarkyctl-web.service",
            ("User=snarkyctl", "Group=snarkyctl", "NoNewPrivileges=true"),
            "systemd.web",
        ),
        _unit_check(
            unit_dir / "snarkyctl-control.service",
            ("User=root", "Group=root", "NoNewPrivileges=true"),
            "systemd.control",
        ),
        _unit_check(
            unit_dir / "snarkyctl-control.socket",
            (
                "ListenStream=/run/snarkyctl/control.sock",
                "SocketUser=root",
                "SocketGroup=snarkyctl",
                "SocketMode=0660",
            ),
            "systemd.socket",
        ),
    ]


def _socket_check(path: Path, group_gid: int | None) -> CheckResult:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return _result("control.socket_live", CheckStatus.SKIP, "control socket is not active")
    except OSError as exc:
        return _result("control.socket_live", CheckStatus.FAIL, f"cannot inspect socket: {exc}")
    safe = (
        stat.S_ISSOCK(metadata.st_mode)
        and metadata.st_uid == 0
        and group_gid is not None
        and metadata.st_gid == group_gid
        and stat.S_IMODE(metadata.st_mode) == 0o660
    )
    return _result(
        "control.socket_live",
        CheckStatus.PASS if safe else CheckStatus.FAIL,
        (
            "live control socket is safe"
            if safe
            else "live control socket has unsafe type or ownership"
        ),
    )


def run_preflight(
    config_path: Path,
    *,
    unit_dir: Path = SYSTEMD_UNIT_DIR,
) -> PreflightReport:
    """Run all read-only checks. Configuration errors are raised to the CLI."""
    config = load_config(config_path)
    checks: list[CheckResult] = [
        _result("config.schema", CheckStatus.PASS, "configuration schema version 1 is valid")
    ]
    checks.extend(_identity_checks())
    try:
        service_group = grp.getgrnam(SYSTEM_GROUP)
        group_gid: int | None = service_group.gr_gid
    except KeyError:
        group_gid = None
    checks.extend(
        (
            _file_security("file.main_config", config_path),
            _file_security("file.targets", config.settings.upstream_vpn.targets_file),
            _file_security(
                "file.auth",
                config.settings.web.auth_file,
                expected_gid=group_gid,
            ),
            _file_security(
                "file.tls_certificate",
                config.settings.web.tls_certificate,
                allow_other_read=True,
            ),
            _file_security(
                "file.tls_private_key",
                config.settings.web.tls_private_key,
                expected_gid=group_gid,
            ),
        )
    )
    checks.extend(_interface_checks(config))
    checks.append(_port_check(config))
    checks.append(_auth_check(config.settings.web.auth_file))
    checks.extend(_tls_checks(config))
    checks.extend(_provider_checks(config))
    checks.extend(_systemd_checks(unit_dir))
    checks.append(_socket_check(config.settings.control.socket_path, group_gid))
    checks.append(
        _result(
            "firewall.policy",
            CheckStatus.SKIP,
            "firewall policy inspection is not implemented; do not activate forwarding controls",
        )
    )
    return PreflightReport(checks=tuple(checks))


def format_report(report: PreflightReport) -> str:
    """Format stable results for an administrator at a terminal."""
    width = max(len(check.status.value) for check in report.checks)
    return "\n".join(
        f"{check.status.value:<{width}}  {check.check_id}: {check.message}"
        for check in report.checks
    )

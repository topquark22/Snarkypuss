"""Typed, read-only status collectors for the local gateway host."""

from __future__ import annotations

import http.client
import ipaddress
import os
import shutil
import ssl
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import SplitResult, urlsplit

from pydantic import BaseModel, ConfigDict, Field

from snarkyctl.providers.base import VpnStatus

SYSTEMCTL_EXECUTABLE = Path("/usr/bin/systemctl")
DNS_SERVICE = "dnsmasq.service"
COMMAND_TIMEOUT_SECONDS = 5.0
MAX_COMMAND_OUTPUT = 16 * 1024


class ComponentFailure(BaseModel):
    """One component that could not contribute to a status snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    component: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    message: str = Field(min_length=1, max_length=512)


class DnsStatus(BaseModel):
    """Observed systemd state of the fixed DNS service."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    service: str
    load_state: str
    active_state: str
    sub_state: str


class SystemStatus(BaseModel):
    """Small, stable set of host resource observations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    uptime_seconds: int = Field(ge=0)
    load_average: tuple[float, float, float]
    memory_total_bytes: int = Field(ge=0)
    memory_available_bytes: int = Field(ge=0)
    root_disk_total_bytes: int = Field(ge=0)
    root_disk_free_bytes: int = Field(ge=0)


class PublicIpStatus(BaseModel):
    """Observed public IPv4 address from a verified HTTPS endpoint."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    address: ipaddress.IPv4Address
    version: int = 4
    checked_at: datetime


class GatewayStatus(BaseModel):
    """Partially degradable status snapshot returned by the control daemon."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    checked_at: datetime
    vpn_status: VpnStatus | None
    dns: DnsStatus | None
    system: SystemStatus | None
    public_ip: PublicIpStatus | None = None
    partial_failures: tuple[ComponentFailure, ...] = ()


class StatusCollectionError(RuntimeError):
    """Controlled failure from one local status collector."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CommandResult:
    """Bounded output from one fixed local status command."""

    returncode: int
    stdout: str
    stderr: str


type CommandRunner = Callable[[Path, tuple[str, ...], float], CommandResult]
type HttpsFetcher = Callable[[str, float], bytes]


def run_command(executable: Path, arguments: tuple[str, ...], timeout: float) -> CommandResult:
    """Run a fixed local command without a shell."""
    try:
        completed = subprocess.run(  # noqa: S603
            [str(executable), *arguments],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={
                "LANG": "C",
                "LC_ALL": "C",
                "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
            },
            shell=False,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise StatusCollectionError(
            "COMMAND_NOT_FOUND", f"required command does not exist: {executable}"
        ) from exc
    except PermissionError as exc:
        raise StatusCollectionError(
            "COMMAND_PERMISSION_DENIED", f"cannot execute required command: {executable}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise StatusCollectionError("COMMAND_TIMEOUT", "status command timed out") from exc
    if (
        len(completed.stdout) > MAX_COMMAND_OUTPUT
        or len(completed.stderr) > MAX_COMMAND_OUTPUT
    ):
        raise StatusCollectionError(
            "COMMAND_OUTPUT_TOO_LARGE", "status command returned too much output"
        )
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def collect_dns_status(runner: CommandRunner = run_command) -> DnsStatus:
    """Return the systemd state of dnsmasq without changing it."""
    result = runner(
        SYSTEMCTL_EXECUTABLE,
        (
            "show",
            DNS_SERVICE,
            "--no-pager",
            "--property=LoadState",
            "--property=ActiveState",
            "--property=SubState",
        ),
        COMMAND_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise StatusCollectionError(
            "DNS_STATUS_FAILED", _command_failure("dnsmasq status query failed", result)
        )
    fields = _parse_key_values(result.stdout)
    required = ("LoadState", "ActiveState", "SubState")
    if any(not fields.get(name) for name in required):
        raise StatusCollectionError(
            "DNS_STATUS_INVALID", "systemd returned incomplete dnsmasq status"
        )
    return DnsStatus(
        service=DNS_SERVICE,
        load_state=fields["LoadState"],
        active_state=fields["ActiveState"],
        sub_state=fields["SubState"],
    )


def collect_public_ip(
    url: str,
    timeout_seconds: float,
    fetcher: HttpsFetcher | None = None,
) -> PublicIpStatus:
    """Retrieve and validate one public IPv4 address over verified HTTPS."""
    active_fetcher = fetcher or _https_get
    try:
        payload = active_fetcher(url, timeout_seconds)
        if len(payload) > 128:
            raise StatusCollectionError(
                "PUBLIC_IP_RESPONSE_INVALID", "public-IP service returned too much data"
            )
        address = ipaddress.ip_address(payload.decode("ascii").strip())
    except StatusCollectionError:
        raise
    except UnicodeError as exc:
        raise StatusCollectionError(
            "PUBLIC_IP_RESPONSE_INVALID", "public-IP service returned non-ASCII data"
        ) from exc
    except ValueError as exc:
        raise StatusCollectionError(
            "PUBLIC_IP_RESPONSE_INVALID", "public-IP service did not return an IP address"
        ) from exc
    if not isinstance(address, ipaddress.IPv4Address):
        raise StatusCollectionError(
            "PUBLIC_IP_RESPONSE_INVALID", "public-IP service did not return an IPv4 address"
        )
    return PublicIpStatus(address=address, checked_at=datetime.now(UTC))


def collect_system_status(
    *,
    uptime_path: Path = Path("/proc/uptime"),
    meminfo_path: Path = Path("/proc/meminfo"),
    load_average: Callable[[], tuple[float, float, float]] = os.getloadavg,
    disk_usage: Callable[[str], shutil._ntuple_diskusage] = shutil.disk_usage,
) -> SystemStatus:
    """Read host health from procfs and the root filesystem."""
    try:
        uptime_text = uptime_path.read_text(encoding="ascii")
        uptime_seconds = int(float(uptime_text.split()[0]))
        memory = _parse_meminfo(meminfo_path.read_text(encoding="ascii"))
        disk = disk_usage("/")
        loads = load_average()
    except (OSError, ValueError, IndexError, KeyError) as exc:
        raise StatusCollectionError(
            "SYSTEM_STATUS_FAILED", "could not read local system health"
        ) from exc
    return SystemStatus(
        uptime_seconds=uptime_seconds,
        load_average=loads,
        memory_total_bytes=memory["MemTotal"] * 1024,
        memory_available_bytes=memory["MemAvailable"] * 1024,
        root_disk_total_bytes=disk.total,
        root_disk_free_bytes=disk.free,
    )


def collect_local_status() -> tuple[DnsStatus | None, SystemStatus | None, list[ComponentFailure]]:
    """Collect independent local components and retain controlled failures."""
    failures: list[ComponentFailure] = []
    dns: DnsStatus | None
    system: SystemStatus | None
    try:
        dns = collect_dns_status()
    except StatusCollectionError as exc:
        dns = None
        failures.append(ComponentFailure(component="dns", code=exc.code, message=str(exc)))
    try:
        system = collect_system_status()
    except StatusCollectionError as exc:
        system = None
        failures.append(ComponentFailure(component="system", code=exc.code, message=str(exc)))
    return dns, system, failures


def new_gateway_status(
    *,
    vpn_status: VpnStatus | None,
    public_ip: PublicIpStatus | None,
    dns: DnsStatus | None,
    system: SystemStatus | None,
    partial_failures: list[ComponentFailure],
) -> GatewayStatus:
    """Create one timestamped immutable gateway snapshot."""
    return GatewayStatus(
        checked_at=datetime.now(UTC),
        vpn_status=vpn_status,
        public_ip=public_ip,
        dns=dns,
        system=system,
        partial_failures=tuple(partial_failures),
    )


def _parse_key_values(output: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in output.splitlines():
        key, separator, value = line.partition("=")
        if separator and key and value:
            fields[key] = value
    return fields


def _parse_meminfo(output: str) -> dict[str, int]:
    fields: dict[str, int] = {}
    for line in output.splitlines():
        name, separator, remainder = line.partition(":")
        if not separator:
            continue
        parts = remainder.split()
        if len(parts) == 2 and parts[1] == "kB":
            fields[name] = int(parts[0])
    return {"MemTotal": fields["MemTotal"], "MemAvailable": fields["MemAvailable"]}


def _command_failure(prefix: str, result: CommandResult) -> str:
    raw = result.stderr.strip() or result.stdout.strip()
    printable = "".join(character if character.isprintable() else " " for character in raw)
    detail = " ".join(printable.split())
    if not detail:
        return f"{prefix} with exit status {result.returncode}"
    detail = detail[:400]
    return f"{prefix} with exit status {result.returncode}: {detail}"


def _https_get(url: str, timeout_seconds: float) -> bytes:
    parsed = urlsplit(url)
    _validate_https_endpoint(parsed)
    host = parsed.hostname
    assert host is not None
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    connection = http.client.HTTPSConnection(
        host,
        port=parsed.port,
        timeout=timeout_seconds,
        context=ssl.create_default_context(),
    )
    try:
        connection.request(
            "GET",
            path,
            headers={
                "Accept": "text/plain",
                "User-Agent": "SnarkyCtl/0.1",
            },
        )
        response = connection.getresponse()
        if response.status != 200:
            raise StatusCollectionError(
                "PUBLIC_IP_HTTP_FAILED",
                f"public-IP service returned HTTP {response.status}",
            )
        payload = response.read(129)
        if len(payload) > 128:
            raise StatusCollectionError(
                "PUBLIC_IP_RESPONSE_INVALID", "public-IP service returned too much data"
            )
        return payload
    except ssl.SSLCertVerificationError as exc:
        raise StatusCollectionError(
            "PUBLIC_IP_TLS_FAILED",
            "public-IP service certificate verification failed",
        ) from exc
    except (OSError, http.client.HTTPException) as exc:
        raise StatusCollectionError(
            "PUBLIC_IP_REQUEST_FAILED", "public-IP service request failed"
        ) from exc
    finally:
        connection.close()


def _validate_https_endpoint(parsed: SplitResult) -> None:
    try:
        parsed.port
    except ValueError as exc:
        raise StatusCollectionError(
            "PUBLIC_IP_URL_INVALID", "public-IP endpoint contains an invalid port"
        ) from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise StatusCollectionError(
            "PUBLIC_IP_URL_INVALID", "public-IP endpoint is not a safe HTTPS URL"
        )

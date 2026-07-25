"""Read-only Mullvad CLI adapter.

Phase 2 deliberately supports inspection only. Mullvad continues to own its
tunnel, routes, DNS, firewall, account, and Lockdown mode.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from snarkyctl.providers.base import (
    GatewayMode,
    ProviderCapabilities,
    ProviderError,
    ProviderPreflightCheck,
    ProviderPreflightStatus,
    VpnProvider,
    VpnSettings,
    VpnState,
    VpnStatus,
    VpnTarget,
)

MULLVAD_EXECUTABLE = Path("/usr/bin/mullvad")
DEFAULT_TIMEOUT_SECONDS = 15.0
MAX_OUTPUT_LENGTH = 64 * 1024
MAX_ERROR_DETAIL_LENGTH = 512
MAX_FIELD_LENGTH = 256
INTERFACE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,14}$")
VERSION_PATTERN = re.compile(r"^[0-9]{4}\.[0-9]+(?:-[A-Za-z0-9.-]+)?$")


@dataclass(frozen=True)
class CommandResult:
    """Bounded result from one Mullvad CLI invocation."""

    returncode: int
    stdout: str
    stderr: str


type CommandRunner = Callable[[Path, Sequence[str], float], CommandResult]


class MullvadAccountState(StrEnum):
    """Authentication state without retaining the Mullvad account number."""

    LOGGED_IN = "LOGGED_IN"
    LOGGED_OUT = "LOGGED_OUT"
    REVOKED = "REVOKED"
    UNKNOWN = "UNKNOWN"


class MullvadVersionInfo(BaseModel):
    """Non-sensitive fields reported by ``mullvad version``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cli_version: str
    daemon_version: str | None = None
    supported: bool


def _bounded_detail(result: CommandResult) -> str | None:
    output = result.stderr.strip() or result.stdout.strip()
    if not output:
        return None
    printable = "".join(character if character.isprintable() else " " for character in output)
    detail = " ".join(printable.split())
    if not detail:
        return None
    if len(detail) > MAX_ERROR_DETAIL_LENGTH:
        return detail[: MAX_ERROR_DETAIL_LENGTH - 3] + "..."
    return detail


def run_command(executable: Path, arguments: Sequence[str], timeout: float) -> CommandResult:
    """Run the fixed Mullvad executable without a shell and bound all output."""
    environment = os.environ.copy()
    environment.update(
        {
            "LANG": "C",
            "LC_ALL": "C",
            "NO_COLOR": "1",
            "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
        }
    )
    try:
        completed = subprocess.run(  # noqa: S603 - executable and argv are constrained here
            [str(executable), *arguments],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            shell=False,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise ProviderError(
            "PROVIDER_UNAVAILABLE", f"Mullvad executable does not exist at {executable}"
        ) from exc
    except PermissionError as exc:
        raise ProviderError(
            "PROVIDER_PERMISSION_DENIED", f"Mullvad executable cannot be run at {executable}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ProviderError("PROVIDER_TIMEOUT", "Mullvad command timed out") from exc
    stdout = completed.stdout[: MAX_OUTPUT_LENGTH + 1]
    stderr = completed.stderr[: MAX_OUTPUT_LENGTH + 1]
    if len(stdout) > MAX_OUTPUT_LENGTH or len(stderr) > MAX_OUTPUT_LENGTH:
        raise ProviderError("PROVIDER_OUTPUT_TOO_LARGE", "Mullvad command output was too large")
    return CommandResult(returncode=completed.returncode, stdout=stdout, stderr=stderr)


def _mapping(value: Any, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ProviderError("PROVIDER_OUTPUT_INVALID", f"Mullvad {field} is not an object")
    return value


def _bounded_string(value: Any, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > MAX_FIELD_LENGTH:
        raise ProviderError("PROVIDER_OUTPUT_INVALID", f"Mullvad {field} is invalid")
    return value


def parse_status(output: str) -> VpnStatus:
    """Parse the documented JSON form of ``mullvad status``."""
    candidate = output.strip()
    if not candidate:
        raise ProviderError("UNPARSEABLE_STATUS", "Mullvad returned an empty status")
    if candidate.startswith("Warning:"):
        _warning, separator, candidate = candidate.partition("\n")
        if not separator or not candidate.strip():
            raise ProviderError(
                "UNPARSEABLE_STATUS", "Mullvad returned unexpected status output"
            )
        candidate = candidate.strip()
    try:
        document = json.loads(candidate)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ProviderError("UNPARSEABLE_STATUS", "Mullvad returned invalid status JSON") from exc
    root = _mapping(document, field="status")
    raw_state = root.get("state")
    if not isinstance(raw_state, str):
        raise ProviderError("UNPARSEABLE_STATUS", "Mullvad status has no valid state")
    states = {
        "disconnected": VpnState.DISCONNECTED,
        "connecting": VpnState.CONNECTING,
        "connected": VpnState.CONNECTED,
        "disconnecting": VpnState.DISCONNECTING,
        "error": VpnState.FAILED,
    }
    try:
        state = states[raw_state]
    except KeyError as exc:
        raise ProviderError("UNPARSEABLE_STATUS", "Mullvad returned an unknown state") from exc

    details_value = root.get("details")
    details = (
        _mapping(details_value, field="status details")
        if isinstance(details_value, dict)
        else {}
    )
    location_value = details.get("location")
    location = (
        _mapping(location_value, field="location")
        if isinstance(location_value, dict)
        else {}
    )
    endpoint_value = details.get("endpoint")
    endpoint = (
        _mapping(endpoint_value, field="endpoint")
        if isinstance(endpoint_value, dict)
        else {}
    )

    hostname = _bounded_string(location.get("hostname"), field="relay hostname")
    country = _bounded_string(location.get("country"), field="country")
    city = _bounded_string(location.get("city"), field="city")
    interface = _bounded_string(endpoint.get("tunnel_interface"), field="tunnel interface")
    if interface is not None and INTERFACE_PATTERN.fullmatch(interface) is None:
        raise ProviderError("PROVIDER_OUTPUT_INVALID", "Mullvad tunnel interface is invalid")

    safe_details: dict[str, str] = {}
    for key, value in (("hostname", hostname), ("country", country), ("city", city)):
        if value is not None:
            safe_details[key] = value

    locked_down = details.get("locked_down")
    if locked_down is not None and not isinstance(locked_down, bool):
        raise ProviderError("PROVIDER_OUTPUT_INVALID", "Mullvad locked_down is invalid")
    protection = locked_down if state is VpnState.DISCONNECTED else None
    if state is VpnState.CONNECTED:
        gateway_mode = GatewayMode.VPN
    elif state is VpnState.DISCONNECTED and protection is True:
        gateway_mode = GatewayMode.LOCKED
    elif state is VpnState.DISCONNECTED and protection is False:
        gateway_mode = GatewayMode.DIRECT
    else:
        gateway_mode = GatewayMode.UNKNOWN

    return VpnStatus(
        state=state,
        provider="mullvad",
        gateway_mode=gateway_mode,
        leak_protection_active=protection,
        display_name=hostname,
        interface=interface,
        diagnostic_code="MULLVAD_TUNNEL_ERROR" if state is VpnState.FAILED else None,
        details=safe_details,
    )


def parse_lockdown_mode(output: str) -> bool:
    """Parse the fixed output from ``mullvad lockdown-mode get``."""
    prefix = "Block traffic when the VPN is disconnected:"
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if len(lines) != 1 or not lines[0].startswith(prefix):
        raise ProviderError(
            "PROVIDER_OUTPUT_INVALID", "Mullvad returned invalid Lockdown mode output"
        )
    value = lines[0][len(prefix) :].strip().casefold()
    if value == "on":
        return True
    if value == "off":
        return False
    raise ProviderError(
        "PROVIDER_OUTPUT_INVALID", "Mullvad returned an unknown Lockdown mode"
    )


def parse_version(output: str) -> MullvadVersionInfo:
    """Parse non-sensitive fields from ``mullvad version``."""
    fields: dict[str, str] = {}
    for line in output.splitlines():
        key, separator, value = line.partition(":")
        if separator:
            fields[key.strip().casefold()] = value.strip()
    cli_version = fields.get("current version")
    daemon_version = fields.get("mullvad-daemon version")
    supported = fields.get("is supported", "").casefold()
    if (
        cli_version is None
        or VERSION_PATTERN.fullmatch(cli_version) is None
        or (
            daemon_version is not None
            and VERSION_PATTERN.fullmatch(daemon_version) is None
        )
        or supported not in {"true", "false"}
    ):
        raise ProviderError("PROVIDER_OUTPUT_INVALID", "Mullvad returned invalid version output")
    return MullvadVersionInfo(
        cli_version=cli_version,
        daemon_version=daemon_version,
        supported=supported == "true",
    )


def parse_account_state(output: str) -> MullvadAccountState:
    """Classify account state without returning or retaining an account number."""
    normalized = output.casefold()
    if "not logged in on any account" in normalized:
        return MullvadAccountState.LOGGED_OUT
    if "device has been revoked" in normalized:
        return MullvadAccountState.REVOKED
    if any(line.strip().startswith("Mullvad account:") for line in output.splitlines()):
        return MullvadAccountState.LOGGED_IN
    return MullvadAccountState.UNKNOWN


class MullvadProvider(VpnProvider):
    """Built-in but unregistered read-only adapter for the Mullvad Linux CLI."""

    name = "mullvad"
    capabilities = ProviderCapabilities(
        connect=False,
        disconnect=False,
        target_selection=False,
        server_details=True,
        leak_protection_status=True,
        leak_protection_configuration=False,
        locked_mode=False,
        direct_mode=False,
    )

    def __init__(
        self,
        *,
        executable: Path | None = MULLVAD_EXECUTABLE,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        runner: CommandRunner = run_command,
    ) -> None:
        self._executable = executable or MULLVAD_EXECUTABLE
        self._timeout_seconds = timeout_seconds
        self._runner = runner

    def _run(self, *arguments: str) -> CommandResult:
        result = self._runner(self._executable, arguments, self._timeout_seconds)
        if result.returncode != 0:
            message = f"Mullvad command failed with exit status {result.returncode}"
            if detail := _bounded_detail(result):
                message = f"{message}: {detail}"
            raise ProviderError("PROVIDER_COMMAND_FAILED", message)
        return result

    def status(self) -> VpnStatus:
        return parse_status(self._run("status", "--json").stdout)

    def settings(self) -> VpnSettings:
        lockdown = parse_lockdown_mode(self._run("lockdown-mode", "get").stdout)
        return VpnSettings(
            provider=self.name,
            leak_protection_enabled=lockdown,
        )

    def connect(self, target: VpnTarget) -> VpnStatus:
        del target
        raise ProviderError(
            "UNSUPPORTED_OPERATION",
            "Mullvad connection control is not enabled in this release.",
        )

    def disconnect(self) -> VpnStatus:
        raise ProviderError(
            "UNSUPPORTED_OPERATION",
            "Mullvad disconnection control is not enabled in this release.",
        )

    def set_leak_protection(self, enabled: bool) -> VpnSettings:
        del enabled
        raise ProviderError(
            "UNSUPPORTED_OPERATION",
            "Mullvad Lockdown mode control is not enabled in this release.",
        )

    def preflight(self) -> tuple[ProviderPreflightCheck, ...]:
        """Inspect Mullvad prerequisites without changing provider state."""
        if not self._executable.is_file() or not os.access(self._executable, os.X_OK):
            return (
                ProviderPreflightCheck(
                    check_id="provider.mullvad.executable",
                    status=ProviderPreflightStatus.FAIL,
                    message=f"Mullvad executable is not runnable at {self._executable}",
                ),
            )

        checks = [
            ProviderPreflightCheck(
                check_id="provider.mullvad.executable",
                status=ProviderPreflightStatus.PASS,
                message=f"Mullvad executable found at {self._executable}",
            )
        ]
        try:
            version = parse_version(self._run("version").stdout)
        except ProviderError as exc:
            checks.append(
                ProviderPreflightCheck(
                    check_id="provider.mullvad.version",
                    status=ProviderPreflightStatus.FAIL,
                    message=f"Cannot verify Mullvad version: {exc.code}",
                )
            )
            return tuple(checks)
        checks.append(
            ProviderPreflightCheck(
                check_id="provider.mullvad.version",
                status=(
                    ProviderPreflightStatus.PASS
                    if version.supported
                    else ProviderPreflightStatus.FAIL
                ),
                message=(
                    f"Mullvad {version.cli_version} is supported"
                    if version.supported
                    else f"Mullvad {version.cli_version} reports that it is unsupported"
                ),
            )
        )

        try:
            state = self.status()
        except ProviderError as exc:
            checks.append(
                ProviderPreflightCheck(
                    check_id="provider.mullvad.status",
                    status=ProviderPreflightStatus.FAIL,
                    message=f"Cannot read Mullvad status: {exc.code}",
                )
            )
        else:
            checks.append(
                ProviderPreflightCheck(
                    check_id="provider.mullvad.status",
                    status=ProviderPreflightStatus.PASS,
                    message=f"Mullvad status is readable ({state.state.value})",
                )
            )

        try:
            account = parse_account_state(self._run("account", "get").stdout)
        except ProviderError as exc:
            checks.append(
                ProviderPreflightCheck(
                    check_id="provider.mullvad.account",
                    status=ProviderPreflightStatus.FAIL,
                    message=f"Cannot verify Mullvad account state: {exc.code}",
                )
            )
        else:
            account_ok = account is MullvadAccountState.LOGGED_IN
            checks.append(
                ProviderPreflightCheck(
                    check_id="provider.mullvad.account",
                    status=(
                        ProviderPreflightStatus.PASS
                        if account_ok
                        else ProviderPreflightStatus.FAIL
                    ),
                    message=(
                        "Mullvad is logged in"
                        if account_ok
                        else f"Mullvad account state is {account.value}"
                    ),
                )
            )

        try:
            lockdown = self.settings().leak_protection_enabled
        except ProviderError as exc:
            checks.append(
                ProviderPreflightCheck(
                    check_id="provider.mullvad.lockdown",
                    status=ProviderPreflightStatus.FAIL,
                    message=f"Cannot verify Mullvad Lockdown mode: {exc.code}",
                )
            )
        else:
            checks.append(
                ProviderPreflightCheck(
                    check_id="provider.mullvad.lockdown",
                    status=ProviderPreflightStatus.PASS,
                    message=f"Mullvad Lockdown mode is {'on' if lockdown else 'off'}",
                )
            )
        return tuple(checks)

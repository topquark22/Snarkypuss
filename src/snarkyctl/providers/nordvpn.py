"""NordVPN CLI adapter.

The adapter asks NordVPN to connect, disconnect, or report status. NordVPN
continues to own its tunnel, routes, DNS, firewall, and provider configuration.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from snarkyctl.providers.base import (
    ProviderCapabilities,
    ProviderError,
    VpnProvider,
    VpnSettings,
    VpnState,
    VpnStatus,
    VpnTarget,
)

NORDVPN_EXECUTABLE = Path("/usr/bin/nordvpn")
DEFAULT_TIMEOUT_SECONDS = 45.0
MAX_OUTPUT_LENGTH = 64 * 1024
MAX_ERROR_DETAIL_LENGTH = 512
MAX_FIELD_LENGTH = 256
TARGET_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._#-]{0,99}$")


@dataclass(frozen=True)
class CommandResult:
    """Bounded result from one NordVPN CLI invocation."""

    returncode: int
    stdout: str
    stderr: str


type CommandRunner = Callable[[Path, Sequence[str], float], CommandResult]


def _error_detail(result: CommandResult) -> str | None:
    """Return bounded, single-line diagnostic text from a failed command."""
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
    """Run one fixed executable without a shell and return bounded text."""
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
            "PROVIDER_UNAVAILABLE", f"NordVPN executable does not exist at {executable}"
        ) from exc
    except PermissionError as exc:
        raise ProviderError(
            "PROVIDER_PERMISSION_DENIED", f"NordVPN executable cannot be run at {executable}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ProviderError("PROVIDER_TIMEOUT", "NordVPN command timed out") from exc
    stdout = completed.stdout[: MAX_OUTPUT_LENGTH + 1]
    stderr = completed.stderr[: MAX_OUTPUT_LENGTH + 1]
    if len(stdout) > MAX_OUTPUT_LENGTH or len(stderr) > MAX_OUTPUT_LENGTH:
        raise ProviderError("PROVIDER_OUTPUT_TOO_LARGE", "NordVPN command output was too large")
    return CommandResult(returncode=completed.returncode, stdout=stdout, stderr=stderr)


def _parse_fields(output: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in output.splitlines():
        key, separator, value = line.partition(":")
        if not separator:
            continue
        normalized = key.strip().casefold().replace("-", "_").replace(" ", "_")
        field_value = value.strip()
        if len(normalized) > MAX_FIELD_LENGTH or len(field_value) > MAX_FIELD_LENGTH:
            raise ProviderError("PROVIDER_OUTPUT_INVALID", "NordVPN returned an oversized field")
        if normalized and field_value:
            fields[normalized] = field_value
    return fields


def parse_status(output: str) -> VpnStatus:
    """Normalize the stable label/value output from ``nordvpn status``."""
    fields = _parse_fields(output)
    raw_state = fields.get("status", "").casefold()
    states = {
        "connected": VpnState.CONNECTED,
        "connecting": VpnState.CONNECTING,
        "disconnected": VpnState.DISCONNECTED,
        "disconnecting": VpnState.DISCONNECTING,
    }
    try:
        state = states[raw_state]
    except KeyError as exc:
        raise ProviderError("UNPARSEABLE_STATUS", "NordVPN returned an unknown status") from exc

    detail_keys = (
        "server",
        "hostname",
        "ip",
        "country",
        "city",
        "current_technology",
        "current_protocol",
        "post_quantum_vpn",
        "transfer",
        "uptime",
    )
    details = {key: fields[key] for key in detail_keys if key in fields}
    technology = fields.get("current_technology", "").casefold()
    interface = "nordlynx" if technology == "nordlynx" else None
    return VpnStatus(
        state=state,
        provider="nordvpn",
        display_name=fields.get("server") or fields.get("hostname"),
        interface=interface,
        details=details,
    )


def _parse_toggle(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = value.casefold()
    if normalized in {"enabled", "on", "true", "1"}:
        return True
    if normalized in {"disabled", "off", "false", "0"}:
        return False
    return None


def parse_settings(output: str) -> VpnSettings:
    """Normalize safety-relevant fields from ``nordvpn settings``."""
    fields = _parse_fields(output)
    return VpnSettings(
        provider="nordvpn",
        leak_protection_enabled=_parse_toggle(fields.get("kill_switch")),
        technology=fields.get("technology"),
        routing_enabled=_parse_toggle(fields.get("routing")),
        firewall_enabled=_parse_toggle(fields.get("firewall")),
        firewall_mark=fields.get("firewall_mark"),
    )


class NordVpnProvider(VpnProvider):
    """Built-in adapter for the NordVPN Linux CLI."""

    name = "nordvpn"
    capabilities = ProviderCapabilities(
        connect=True,
        disconnect=True,
        target_selection=True,
        server_details=True,
        leak_protection_configuration=True,
    )

    def __init__(
        self,
        *,
        executable: Path = NORDVPN_EXECUTABLE,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        runner: CommandRunner = run_command,
    ) -> None:
        self._executable = executable
        self._timeout_seconds = timeout_seconds
        self._runner = runner

    def _run(self, *arguments: str) -> CommandResult:
        result = self._runner(self._executable, arguments, self._timeout_seconds)
        if result.returncode != 0:
            message = f"NordVPN command failed with exit status {result.returncode}"
            if detail := _error_detail(result):
                message = f"{message}: {detail}"
            raise ProviderError(
                "PROVIDER_COMMAND_FAILED",
                message,
            )
        return result

    def status(self) -> VpnStatus:
        result = self._run("status")
        return parse_status(result.stdout)

    def settings(self) -> VpnSettings:
        result = self._run("settings")
        return parse_settings(result.stdout)

    def connect(self, target: VpnTarget) -> VpnStatus:
        if TARGET_PATTERN.fullmatch(target.provider_target) is None:
            raise ProviderError("INVALID_TARGET", "NordVPN target contains unsupported characters")
        self._run("connect", target.provider_target)
        status = self.status()
        return status.model_copy(
            update={"target": target.alias, "display_name": status.display_name or target.label}
        )

    def disconnect(self) -> VpnStatus:
        self._run("disconnect")
        return self.status()

    def set_leak_protection(self, enabled: bool) -> VpnSettings:
        self._run("set", "killswitch", "on" if enabled else "off")
        return self.settings()

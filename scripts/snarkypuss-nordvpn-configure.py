#!/usr/bin/env python3
"""Configure NordVPN policy required by the Snarkypuss reference gateway."""

from __future__ import annotations

import argparse
import configparser
import ipaddress
import os
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path


NORDVPN_EXECUTABLE = Path("/usr/bin/nordvpn")
DEFAULT_CONFIG_PATH = Path("/etc/snarkypuss-setup.conf")
COMMAND_TIMEOUT_SECONDS = 45.0
MAX_OUTPUT_LENGTH = 64 * 1024
_DUPLICATE_PATTERN = re.compile(
    r"\b(?:already|exists|present|added|allowlisted|whitelisted)\b", re.IGNORECASE
)


class NordVpnSetupError(RuntimeError):
    """Raised when NordVPN setup cannot be completed safely."""


@dataclass(frozen=True)
class GatewayPolicy:
    """NordVPN policy values derived from the Snarkypuss gateway configuration."""

    listen_port: int
    management_subnet: ipaddress.IPv4Network


@dataclass(frozen=True)
class CommandResult:
    """Bounded result from one NordVPN CLI invocation."""

    returncode: int
    stdout: str
    stderr: str


type Runner = Callable[[Sequence[str]], CommandResult]


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description=(
            "Configure NordVPN for Snarkypuss: NordLynx, autoconnect off, the "
            "WireGuard management exceptions, and Kill Switch on."
        )
    )
    result.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Snarkypuss gateway setup file (default: {DEFAULT_CONFIG_PATH})",
    )
    mode = result.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="print the intended NordVPN changes without modifying provider state",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="apply and verify the NordVPN settings",
    )
    result.add_argument(
        "--console-confirmed",
        action="store_true",
        help="assert that independent VPS console/LISH recovery access is available",
    )
    return result


def read_gateway_policy(path: Path) -> GatewayPolicy:
    document = configparser.ConfigParser(interpolation=None, strict=True)
    document.optionxform = str.lower
    try:
        with path.open(encoding="utf-8") as stream:
            document.read_file(stream)
    except (OSError, configparser.Error) as exc:
        raise NordVpnSetupError(f"cannot read gateway configuration {path}: {exc}") from exc

    if "gateway" not in document:
        raise NordVpnSetupError("gateway configuration has no [gateway] section")
    section = document["gateway"]
    try:
        listen_port = int(section["listen_port"].strip())
        server = ipaddress.IPv4Interface(section["server_address"].strip())
    except KeyError as exc:
        raise NordVpnSetupError(f"gateway configuration is missing {exc.args[0]}") from exc
    except ValueError as exc:
        raise NordVpnSetupError(f"invalid gateway value: {exc}") from exc

    if not 1 <= listen_port <= 65535:
        raise NordVpnSetupError("listen_port must be between 1 and 65535")
    return GatewayPolicy(listen_port=listen_port, management_subnet=server.network)


def run_command(arguments: Sequence[str]) -> CommandResult:
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
        completed = subprocess.run(  # noqa: S603 - fixed reviewed executable and argv
            [str(NORDVPN_EXECUTABLE), *arguments],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            shell=False,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise NordVpnSetupError(
            f"NordVPN executable does not exist at {NORDVPN_EXECUTABLE}"
        ) from exc
    except PermissionError as exc:
        raise NordVpnSetupError(
            f"NordVPN executable cannot be run at {NORDVPN_EXECUTABLE}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise NordVpnSetupError("NordVPN command timed out") from exc

    stdout = completed.stdout[: MAX_OUTPUT_LENGTH + 1]
    stderr = completed.stderr[: MAX_OUTPUT_LENGTH + 1]
    if len(stdout) > MAX_OUTPUT_LENGTH or len(stderr) > MAX_OUTPUT_LENGTH:
        raise NordVpnSetupError("NordVPN command output was too large")
    return CommandResult(completed.returncode, stdout, stderr)


def _detail(result: CommandResult) -> str:
    raw = result.stderr.strip() or result.stdout.strip()
    printable = "".join(character if character.isprintable() else " " for character in raw)
    return " ".join(printable.split())[:512]


def checked(runner: Runner, *arguments: str, duplicate_ok: bool = False) -> CommandResult:
    result = runner(arguments)
    if result.returncode == 0:
        return result
    detail = _detail(result)
    if duplicate_ok and _DUPLICATE_PATTERN.search(detail):
        return result
    message = f"nordvpn {' '.join(arguments)} failed with exit status {result.returncode}"
    if detail:
        message += f": {detail}"
    raise NordVpnSetupError(message)


def detect_allowlist_command(runner: Runner) -> str:
    """Return the installed NordVPN exception command: allowlist or legacy whitelist."""
    help_result = runner(("help",))
    combined = f"{help_result.stdout}\n{help_result.stderr}".casefold()
    if re.search(r"\ballowlist\b", combined):
        return "allowlist"
    if re.search(r"\bwhitelist\b", combined):
        return "whitelist"

    for candidate in ("allowlist", "whitelist"):
        probe = runner((candidate, "--help"))
        text = f"{probe.stdout}\n{probe.stderr}".casefold()
        if probe.returncode == 0 and "unknown command" not in text and "not found" not in text:
            return candidate
    raise NordVpnSetupError(
        "installed NordVPN client exposes neither allowlist nor legacy whitelist commands"
    )


def exception_commands(policy: GatewayPolicy, command: str) -> tuple[tuple[str, ...], ...]:
    port = str(policy.listen_port)
    subnet = str(policy.management_subnet)
    if command == "allowlist":
        return (
            ("allowlist", "add", "port", port, "protocol", "UDP"),
            ("allowlist", "add", "subnet", subnet),
        )
    if command == "whitelist":
        return (
            ("whitelist", "add", "port", port),
            ("whitelist", "add", "subnet", subnet),
        )
    raise NordVpnSetupError(f"unsupported NordVPN exception command: {command}")


def _parse_fields(output: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in output.splitlines():
        key, separator, value = line.partition(":")
        if not separator:
            continue
        normalized = key.strip().casefold().replace("-", "_").replace(" ", "_")
        if normalized:
            fields[normalized] = value.strip()
    return fields


def _toggle(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = value.casefold()
    if normalized in {"enabled", "enable", "on", "true", "1"}:
        return True
    if normalized in {"disabled", "disable", "off", "false", "0"}:
        return False
    return None


def verify_settings(output: str) -> None:
    fields = _parse_fields(output)
    technology = fields.get("technology", "").casefold()
    if technology != "nordlynx":
        raise NordVpnSetupError(
            f"NordVPN settings did not verify NordLynx technology (reported {technology or 'unknown'})"
        )
    if _toggle(fields.get("kill_switch")) is not True:
        raise NordVpnSetupError("NordVPN settings did not verify Kill Switch enabled")
    autoconnect = fields.get("auto_connect") or fields.get("autoconnect")
    if _toggle(autoconnect) is not False:
        raise NordVpnSetupError("NordVPN settings did not verify auto-connect disabled")


def plan(policy: GatewayPolicy, exception_command: str) -> tuple[tuple[str, ...], ...]:
    return (
        ("set", "technology", "NordLynx"),
        ("set", "autoconnect", "off"),
        *exception_commands(policy, exception_command),
        ("set", "killswitch", "on"),
    )


def print_plan(commands: Sequence[Sequence[str]], *, exception_command: str) -> None:
    print("Snarkypuss NordVPN configuration plan")
    print(f"Detected management-exception command: {exception_command}")
    for command in commands:
        print("  nordvpn " + " ".join(command))


def apply_policy(policy: GatewayPolicy, runner: Runner = run_command) -> None:
    exception_command = detect_allowlist_command(runner)
    commands = plan(policy, exception_command)
    print_plan(commands, exception_command=exception_command)
    for command in commands:
        is_exception = command[0] in {"allowlist", "whitelist"}
        result = checked(runner, *command, duplicate_ok=is_exception)
        if result.returncode != 0 and is_exception:
            print("UNCHANGED: management exception is already present")
        else:
            print("APPLIED: nordvpn " + " ".join(command))

    settings = checked(runner, "settings")
    verify_settings(settings.stdout)
    print("VERIFIED: NordLynx, Kill Switch on, and auto-connect off")
    print(
        "The management exceptions were accepted. Complete the documented fail-closed test "
        "before relying on the gateway."
    )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        policy = read_gateway_policy(arguments.config)
        exception_command = detect_allowlist_command(run_command)
        commands = plan(policy, exception_command)
        if arguments.dry_run:
            print_plan(commands, exception_command=exception_command)
            print("No NordVPN setting was changed.")
            return 0
        if os.geteuid() != 0:
            raise NordVpnSetupError("--apply must run as root")
        if not arguments.console_confirmed:
            raise NordVpnSetupError(
                "--apply requires --console-confirmed after verifying LISH/console recovery access"
            )
        apply_policy(policy)
        return 0
    except NordVpnSetupError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

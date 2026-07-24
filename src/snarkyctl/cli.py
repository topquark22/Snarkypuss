"""Command-line entry point for SnarkyCtl administration tools."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from snarkyctl import __version__
from snarkyctl.config import DEFAULT_CONFIG_PATH, ConfigError, load_config
from snarkyctl.control.client import ControlClient, ControlClientError
from snarkyctl.preflight import format_report, run_preflight
from snarkyctl.providers.base import GatewayMode, VpnStatus
from snarkyctl.status import GatewayStatus


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level command-line parser."""
    parser = argparse.ArgumentParser(
        prog="snarkyctl",
        description="Administration tools for the SnarkyCtl VPN gateway control plane.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    commands = parser.add_subparsers(dest="command")
    validate = commands.add_parser(
        "validate-config",
        help="validate the main configuration and target allowlist",
    )
    validate.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"main configuration path (default: {DEFAULT_CONFIG_PATH})",
    )
    preflight = commands.add_parser(
        "preflight",
        help="run read-only deployment safety checks before service activation",
    )
    preflight.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"main configuration path (default: {DEFAULT_CONFIG_PATH})",
    )
    preflight.add_argument(
        "--json",
        action="store_true",
        help="emit the versioned machine-readable report",
    )
    for name, help_text in (
        ("status", "show current upstream VPN and gateway status"),
        ("disconnect", "safely disconnect the upstream VPN"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--json", action="store_true", help="emit the complete JSON response")
    connect = commands.add_parser("connect", help="connect to a configured target alias")
    connect.add_argument("target", help="target alias from the root-owned allowlist")
    connect.add_argument("--json", action="store_true", help="emit the complete JSON response")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "validate-config":
        try:
            loaded = load_config(args.config)
        except ConfigError as exc:
            print(f"snarkyctl: {exc}", file=sys.stderr)
            return 2
        print(
            f"Configuration is valid: provider={loaded.settings.upstream_vpn.provider}, "
            f"targets={len(loaded.targets.targets)}"
        )
    elif args.command == "preflight":
        try:
            report = run_preflight(args.config)
        except ConfigError as exc:
            print(f"snarkyctl: {exc}", file=sys.stderr)
            return 2
        print(report.as_json() if args.json else format_report(report))
        return 0 if report.passed else 1
    elif args.command in {"status", "connect", "disconnect"}:
        return _run_control_command(args)
    return 0


def _run_control_command(args: argparse.Namespace) -> int:
    client = ControlClient()
    try:
        if args.command == "status":
            response = client.status()
        elif args.command == "connect":
            response = client.connect(args.target)
        else:
            response = client.disconnect()
    except ControlClientError as exc:
        if args.json:
            print(json.dumps({"success": False, "error_code": exc.code, "message": str(exc)}))
        else:
            print(f"snarkyctl: {exc.code}: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(response.model_dump_json(indent=2))
    elif not response.success:
        print(
            f"snarkyctl: {response.error_code or 'CONTROL_ERROR'}: {response.message}",
            file=sys.stderr,
        )
    else:
        if args.command == "status":
            if response.gateway_status is None:
                print(
                    "snarkyctl: INVALID_RESPONSE: response has no gateway status",
                    file=sys.stderr,
                )
                return 2
            print(_format_gateway_status(response.gateway_status))
        elif response.vpn_status is None:
            print("snarkyctl: INVALID_RESPONSE: response has no VPN status", file=sys.stderr)
            return 2
        else:
            print(response.message)
            print(_format_vpn_status(response.vpn_status))
    return 0 if response.success else 1


def _format_gateway_status(status: GatewayStatus) -> str:
    sections: list[str] = []
    if status.vpn_status is None:
        sections.append("Upstream VPN\n  Status:          Unavailable")
    else:
        sections.append(_format_vpn_status(status.vpn_status))
    if status.dns is None:
        sections.append("DNS\n  Status:          Unavailable")
    else:
        sections.append(
            "\n".join(
                (
                    "DNS",
                    f"  Service:         {status.dns.service}",
                    f"  State:           {status.dns.active_state} ({status.dns.sub_state})",
                )
            )
        )
    if status.system is None:
        sections.append("System\n  Status:          Unavailable")
    else:
        system = status.system
        sections.append(
            "\n".join(
                (
                    "System",
                    f"  Uptime:          {_format_duration(system.uptime_seconds)}",
                    "  Load:            "
                    + " / ".join(f"{value:.2f}" for value in system.load_average),
                    "  Memory available:"
                    f" {_format_bytes(system.memory_available_bytes)}"
                    f" / {_format_bytes(system.memory_total_bytes)}",
                    "  Root disk free:  "
                    f" {_format_bytes(system.root_disk_free_bytes)}"
                    f" / {_format_bytes(system.root_disk_total_bytes)}",
                )
            )
        )
    if status.partial_failures:
        failures = ["Partial failures"]
        failures.extend(
            f"  {failure.component}: {failure.code}: {failure.message}"
            for failure in status.partial_failures
        )
        sections.append("\n".join(failures))
    return "\n\n".join(sections)


def _format_vpn_status(status: VpnStatus) -> str:
    exposure = {
        GatewayMode.DIRECT: "YES — VPS public IP is exposed",
        GatewayMode.VPN: "No",
        GatewayMode.LOCKED: "No — Internet access is blocked",
        GatewayMode.UNKNOWN: "Unknown",
    }[status.gateway_mode]
    values = (
        ("Provider", status.provider),
        ("VPN state", status.state),
        ("Gateway mode", status.gateway_mode),
        ("Target", status.target or "-"),
        ("Server", status.display_name or "-"),
        ("Leak protection", _format_optional_bool(status.leak_protection_active)),
        ("Public exposure", exposure),
    )
    return "\n".join(f"{label + ':':<18}{value}" for label, value in values)


def _format_optional_bool(value: bool | None) -> str:
    if value is None:
        return "Unknown"
    return "Enabled" if value else "Disabled"


def _format_duration(seconds: int) -> str:
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _seconds = divmod(remainder, 60)
    values = []
    if days:
        values.append(f"{days}d")
    if hours or days:
        values.append(f"{hours}h")
    values.append(f"{minutes}m")
    return " ".join(values)


def _format_bytes(value: int) -> str:
    amount = float(value)
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f} {unit}"
        amount /= 1024
    raise AssertionError("unreachable")

"""Command-line entry point for SnarkyCtl administration tools."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from snarkyctl import __version__
from snarkyctl.config import DEFAULT_CONFIG_PATH, ConfigError, load_config
from snarkyctl.control.client import ControlClient, ControlClientError
from snarkyctl.control.protocol import ControlResponse
from snarkyctl.preflight import format_report, run_preflight
from snarkyctl.providers.base import GatewayMode, VpnStatus
from snarkyctl.status import GatewayStatus
from snarkyctl.targets.lifecycle import (
    DEFAULT_TARGET_DATABASE_PATH,
    backup_database,
    check_database,
    initialize_database,
)
from snarkyctl.targets.migration import migrate_yaml_catalogue
from snarkyctl.targets.models import StoredTarget
from snarkyctl.targets.repository import RepositoryError


class _CatalogueReplacementFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    expected_revision: int = Field(ge=0)
    targets: tuple[StoredTarget, ...] = Field(min_length=1, max_length=100)


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
    database = commands.add_parser(
        "targets-db", help="administer the provider target catalogue database"
    )
    database_commands = database.add_subparsers(dest="database_command", required=True)
    for name, help_text in (
        ("initialize", "create and verify an empty database"),
        ("check", "verify permissions, schema, and integrity"),
    ):
        command = database_commands.add_parser(name, help=help_text)
        command.add_argument(
            "--database",
            type=Path,
            default=DEFAULT_TARGET_DATABASE_PATH,
            help=f"database path (default: {DEFAULT_TARGET_DATABASE_PATH})",
        )
    backup = database_commands.add_parser("backup", help="create a consistent database backup")
    backup.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_TARGET_DATABASE_PATH,
        help=f"source database path (default: {DEFAULT_TARGET_DATABASE_PATH})",
    )
    backup.add_argument("--output", type=Path, required=True, help="new backup file path")
    migrate = database_commands.add_parser(
        "migrate", help="explicitly migrate the configured YAML catalogue to SQLite"
    )
    migrate.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"legacy YAML configuration path (default: {DEFAULT_CONFIG_PATH})",
    )
    migrate.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_TARGET_DATABASE_PATH,
        help=f"destination database path (default: {DEFAULT_TARGET_DATABASE_PATH})",
    )
    targets = commands.add_parser("targets", help="inspect or replace the active target catalogue")
    target_commands = targets.add_subparsers(dest="targets_command", required=True)
    for name, help_text in (
        ("list", "list sanitized target aliases and labels"),
        ("schema", "show the active provider selector schema"),
        ("export", "export the editable catalogue as JSON"),
    ):
        command = target_commands.add_parser(name, help=help_text)
        command.add_argument("--json", action="store_true", help="emit JSON")
    replace = target_commands.add_parser(
        "replace", help="replace the complete catalogue from a JSON file"
    )
    replace.add_argument("file", type=Path, help="replacement JSON document")
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
        backend = "yaml" if loaded.targets is not None else "sqlite"
        target_count = len(loaded.targets.targets) if loaded.targets is not None else "stored"
        print(
            f"Configuration is valid: provider={loaded.settings.upstream_vpn.provider}, "
            f"target_backend={backend}, targets={target_count}"
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
    elif args.command == "targets-db":
        return _run_database_command(args)
    elif args.command == "targets":
        return _run_targets_command(args)
    return 0


def _run_database_command(args: argparse.Namespace) -> int:
    try:
        if args.database_command == "initialize":
            initialize_database(args.database)
            message = f"Initialized and verified target database: {args.database}"
        elif args.database_command == "check":
            check_database(args.database)
            message = f"Target database is valid: {args.database}"
        elif args.database_command == "backup":
            backup_database(args.output, args.database)
            message = f"Backed up target database to: {args.output}"
        else:
            result = migrate_yaml_catalogue(args.config, args.database)
            message = (
                f"Migrated {result.migrated_count} targets for {result.provider} "
                f"to revision {result.revision} in {result.database}. "
                "YAML remains authoritative until configuration is switched."
            )
    except (ConfigError, RepositoryError) as exc:
        code = exc.code if isinstance(exc, RepositoryError) else "INVALID_CONFIG"
        print(f"snarkyctl: {code}: {exc}", file=sys.stderr)
        return 2
    print(message)
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


def _run_targets_command(args: argparse.Namespace) -> int:
    client = ControlClient()
    try:
        ordinary = client.targets()
        if not ordinary.success or ordinary.target_catalog is None:
            return _print_control_failure(ordinary)
        provider = ordinary.target_catalog.provider
        if args.targets_command == "list":
            if args.json:
                print(ordinary.target_catalog.model_dump_json(indent=2))
            else:
                for target in ordinary.target_catalog.targets:
                    print(f"{target.alias}\t{target.label}")
            return 0
        if args.targets_command == "schema":
            response = client.target_schema(provider)
            if not response.success or response.provider_target_schema is None:
                return _print_control_failure(response)
            output = response.provider_target_schema.model_dump_json(indent=2)
            print(output)
            return 0
        if args.targets_command == "export":
            response = client.editable_catalogue(provider)
            if not response.success or response.editable_target_catalogue is None:
                return _print_control_failure(response)
            catalogue = response.editable_target_catalogue
            document = {
                "provider": catalogue.provider,
                "expected_revision": catalogue.revision,
                "targets": [target.model_dump(mode="json") for target in catalogue.targets],
            }
            print(json.dumps(document, indent=2))
            return 0
        try:
            replacement_document = _CatalogueReplacementFile.model_validate_json(
                args.file.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, ValidationError) as exc:
            print(f"snarkyctl: INVALID_CATALOG: {exc}", file=sys.stderr)
            return 2
        response = client.replace_catalogue(
            replacement_document.provider,
            replacement_document.expected_revision,
            replacement_document.targets,
        )
        if not response.success or response.editable_target_catalogue is None:
            return _print_control_failure(response)
        print(
            f"Replaced {len(response.editable_target_catalogue.targets)} targets; "
            f"revision={response.editable_target_catalogue.revision}"
        )
        return 0
    except ControlClientError as exc:
        print(f"snarkyctl: {exc.code}: {exc}", file=sys.stderr)
        return 2


def _print_control_failure(response: ControlResponse) -> int:
    error_code = response.error_code or "CONTROL_ERROR"
    print(f"snarkyctl: {error_code}: {response.message}", file=sys.stderr)
    return 1


def _format_gateway_status(status: GatewayStatus) -> str:
    sections: list[str] = []
    if status.vpn_status is None:
        sections.append("Upstream VPN\n  Status:          Unavailable")
    else:
        sections.append(_format_vpn_status(status.vpn_status))
    sections.append(
        "Public exit IPv4:"
        f" {status.public_ip.address if status.public_ip is not None else 'Unavailable'}"
    )
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

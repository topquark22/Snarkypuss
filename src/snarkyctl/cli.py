"""Command-line entry point for SnarkyCtl administration tools."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from snarkyctl import __version__
from snarkyctl.config import DEFAULT_CONFIG_PATH, ConfigError, load_config
from snarkyctl.preflight import format_report, run_preflight


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
    return 0

"""Command-line entry point for SnarkyCtl administration tools."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from snarkyctl import __version__
from snarkyctl.config import DEFAULT_CONFIG_PATH, ConfigError, load_config


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
    return 0

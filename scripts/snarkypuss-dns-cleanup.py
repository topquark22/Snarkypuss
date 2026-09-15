#!/usr/bin/env python3
"""Restore distro dnsmasq configuration after a confirmed Snarkypuss DNS cutover."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path


STOCK_CONFIG = "/etc/dnsmasq.conf"
ORIGINAL_BACKUP = "/etc/dnsmasq.conf.snarkypuss-original"
LEGACY_CONFIG = "/etc/dnsmasq.d/snarkypuss.conf"
LEGACY_DROPIN = "/etc/systemd/system/dnsmasq.service.d/snarkypuss.conf"
NEW_SERVICE = "snarkypuss-dns.service"
LEGACY_SERVICE = "dnsmasq.service"
SNARKYPUSS_BIND_MARKER = "disabled by Snarkypuss; bind-dynamic is used"


class CleanupError(RuntimeError):
    """Legacy DNS cleanup cannot proceed safely."""


def rooted(root: Path, absolute_path: str) -> Path:
    return root / absolute_path.removeprefix("/")


def service_active(unit: str) -> bool:
    return (
        subprocess.run(  # noqa: S603, S607 - fixed reviewed command
            ["systemctl", "is-active", "--quiet", unit],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )


def atomic_restore(source: Path, destination: Path) -> None:
    source_stat = source.stat()
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.snarkypuss-restore.", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        with source.open("rb") as input_stream, os.fdopen(descriptor, "wb") as output_stream:
            while chunk := input_stream.read(64 * 1024):
                output_stream.write(chunk)
            output_stream.flush()
            os.fsync(output_stream.fileno())
        os.chmod(temporary, source_stat.st_mode & 0o7777)
        os.chown(temporary, source_stat.st_uid, source_stat.st_gid)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def cleanup_plan(root: Path) -> tuple[bool, tuple[Path, ...]]:
    stock = rooted(root, STOCK_CONFIG)
    backup = rooted(root, ORIGINAL_BACKUP)
    legacy_paths = tuple(
        path
        for path in (
            rooted(root, LEGACY_CONFIG),
            rooted(root, LEGACY_DROPIN),
        )
        if path.is_file()
    )

    restore_stock = False
    if backup.is_file():
        if not stock.exists():
            restore_stock = True
        elif not stock.is_file():
            raise CleanupError(f"stock dnsmasq path is not a regular file: {stock}")
        elif stock.read_bytes() == backup.read_bytes():
            restore_stock = False
        else:
            current = stock.read_text(encoding="utf-8", errors="replace")
            if SNARKYPUSS_BIND_MARKER not in current:
                raise CleanupError(
                    "current /etc/dnsmasq.conf differs from the saved original but no longer "
                    "contains the Snarkypuss bind marker; refusing to overwrite possible "
                    "administrator changes"
                )
            restore_stock = True
    elif stock.is_file():
        current = stock.read_text(encoding="utf-8", errors="replace")
        if SNARKYPUSS_BIND_MARKER in current:
            raise CleanupError(
                "the Snarkypuss bind modification is present but the saved original "
                "/etc/dnsmasq.conf.snarkypuss-original is missing"
            )

    return restore_stock, legacy_paths


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Clean up the legacy distro-managed dnsmasq path after the dedicated "
            "Snarkypuss DNS service has been accepted."
        )
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="describe cleanup only")
    mode.add_argument("--apply", action="store_true", help="perform cleanup")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("/"),
        help="filesystem root (default: /; useful for staging tests)",
    )
    arguments = parser.parse_args()
    root = arguments.root.resolve()

    try:
        if arguments.apply and root == Path("/") and os.geteuid() != 0:
            raise CleanupError("--apply to / must run as root")

        if root == Path("/"):
            if not service_active(NEW_SERVICE):
                raise CleanupError(
                    f"{NEW_SERVICE} is not active; refusing legacy DNS cleanup before cutover"
                )
            if service_active(LEGACY_SERVICE):
                raise CleanupError(
                    f"{LEGACY_SERVICE} is still active; refusing to alter its configuration"
                )

        restore_stock, legacy_paths = cleanup_plan(root)
        stock = rooted(root, STOCK_CONFIG)
        backup = rooted(root, ORIGINAL_BACKUP)

        print("Snarkypuss legacy DNS cleanup")
        print(f"Mode: {'apply' if arguments.apply else 'dry-run'}")
        if restore_stock:
            print(f"PLAN: restore {stock} from {backup}")
        elif backup.is_file() and stock.is_file() and stock.read_bytes() == backup.read_bytes():
            print(f"PLAN: {stock} already matches the saved original")
        else:
            print("PLAN: no Snarkypuss-owned stock dnsmasq.conf modification to restore")
        for path in legacy_paths:
            print(f"PLAN: remove legacy Snarkypuss file {path}")

        if arguments.dry_run:
            print("No files or services were changed.")
            return 0

        if restore_stock:
            atomic_restore(backup, stock)
            print(f"RESTORED: {stock} from {backup}")
        for path in legacy_paths:
            path.unlink()
            print(f"REMOVED: {path}")

        if root == Path("/"):
            subprocess.run(  # noqa: S603, S607 - fixed reviewed command
                ["systemctl", "daemon-reload"], check=True
            )

        print(
            "Legacy Snarkypuss dnsmasq customization is cleaned up. "
            "The saved original backup is retained for recovery."
        )
        return 0
    except (CleanupError, OSError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

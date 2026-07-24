#!/usr/bin/env python3
"""Migrate an existing Snarkypuss gateway into managed configuration."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_BACKUP_ROOT = "/var/backups/snarkypuss"
MANIFEST_NAME = "migration-manifest.json"
MANAGED_PATHS = (
    "/etc/wireguard/{interface}.conf",
    "/etc/wireguard/{interface}.private.key",
    "/etc/dnsmasq.conf",
    "/etc/dnsmasq.d/snarkypuss.conf",
    "/etc/systemd/system/dnsmasq.service.d/snarkypuss.conf",
    "/etc/sysctl.conf",
    "/etc/sysctl.d/90-snarkypuss.conf",
    "/etc/iptables/rules.v4",
    "/etc/snarkypuss-setup.conf",
    "/etc/snarkypuss/client.pub",
)


class MigrationError(RuntimeError):
    """Existing configuration cannot be migrated safely."""


@dataclass(frozen=True)
class ExistingGateway:
    interface: str
    server_address: str
    listen_port: int
    private_key: str
    fwmark: int
    client_address: str
    client_public_key: str
    persistent_keepalive: int
    legacy_hooks: tuple[str, ...]


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description=(
            "Audit, prepare, or restore a migration from an existing Snarkypuss "
            "gateway. Preparation does not change live networking."
        )
    )
    mode = result.add_mutually_exclusive_group(required=True)
    mode.add_argument("--audit", action="store_true", help="inspect without writing files")
    mode.add_argument(
        "--prepare",
        action="store_true",
        help="back up files and generate inactive managed configuration",
    )
    mode.add_argument(
        "--restore",
        type=Path,
        metavar="BACKUP_DIRECTORY",
        help="restore files captured by a previous --prepare",
    )
    result.add_argument("--tunnel-interface", default="wg0")
    result.add_argument("--protected-egress-interface")
    result.add_argument(
        "--dns-upstreams",
        help="comma-separated DNS server IPs; otherwise discover dnsmasq server= entries",
    )
    result.add_argument(
        "--root",
        type=Path,
        default=Path("/"),
        help="filesystem root (default: /; useful for staging tests)",
    )
    result.add_argument(
        "--backup-root",
        default=DEFAULT_BACKUP_ROOT,
        help=f"absolute backup parent (default: {DEFAULT_BACKUP_ROOT})",
    )
    return result


def rooted(root: Path, absolute_path: str) -> Path:
    return root / absolute_path.removeprefix("/")


def validate_interface(value: str, label: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,15}", value):
        raise MigrationError(f"{label} is not a valid Linux interface name")
    return value


def validate_key(value: str, label: str) -> str:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise MigrationError(f"{label} is not valid base64") from exc
    if len(value) != 44 or len(decoded) != 32:
        raise MigrationError(f"{label} is not a 32-byte WireGuard key")
    return value


def parse_wireguard(path: Path, interface: str, managed_key_path: Path) -> ExistingGateway:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise MigrationError(f"cannot read existing WireGuard configuration {path}: {exc}") from exc

    sections: dict[str, list[tuple[str, str]]] = {"Interface": [], "Peer": []}
    section = ""
    peer_count = 0
    legacy_hooks: list[str] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            if section == "Peer":
                peer_count += 1
            continue
        if "=" not in line or section not in sections:
            continue
        name, value = (part.strip() for part in line.split("=", 1))
        sections[section].append((name.lower(), value))
        if name.lower() in {"postup", "postdown", "preup", "predown"}:
            legacy_hooks.append(name)

    if peer_count != 1:
        raise MigrationError(
            f"{path} must contain exactly one [Peer] section; found {peer_count}"
        )

    def one(section_name: str, option: str, *, required: bool = True) -> str | None:
        values = [
            value
            for name, value in sections[section_name]
            if name == option.lower()
        ]
        if len(values) > 1:
            raise MigrationError(f"duplicate {option} in [{section_name}]")
        if not values:
            if required:
                raise MigrationError(f"missing {option} in [{section_name}]")
            return None
        return values[0]

    inline_key = one("Interface", "PrivateKey", required=False)
    file_key = None
    if managed_key_path.exists():
        try:
            file_key = managed_key_path.read_text(encoding="ascii").strip()
        except OSError as exc:
            raise MigrationError(f"cannot read {managed_key_path}: {exc}") from exc
    if inline_key and file_key and inline_key != file_key:
        raise MigrationError(
            "inline and managed server private keys differ; refusing to choose one"
        )
    private_key = inline_key or file_key
    if not private_key:
        raise MigrationError("existing server private key was not found")

    address = one("Interface", "Address")
    client_address = one("Peer", "AllowedIPs")
    try:
        server_interface = ipaddress.IPv4Interface(str(address).split(",", 1)[0].strip())
        client_interface = ipaddress.IPv4Interface(
            str(client_address).split(",", 1)[0].strip()
        )
    except ValueError as exc:
        raise MigrationError(f"unsupported WireGuard IPv4 address: {exc}") from exc
    if client_interface.ip not in server_interface.network:
        raise MigrationError("client AllowedIPs is outside the server tunnel network")

    try:
        listen_port = int(str(one("Interface", "ListenPort")))
        fwmark = int(str(one("Interface", "FwMark")), 0)
        keepalive_raw = one("Peer", "PersistentKeepalive", required=False)
        keepalive = int(keepalive_raw) if keepalive_raw else 25
    except ValueError as exc:
        raise MigrationError(f"invalid numeric WireGuard setting: {exc}") from exc
    if not 1 <= listen_port <= 65535:
        raise MigrationError("ListenPort must be between 1 and 65535")
    if not 0 <= fwmark <= 0xFFFFFFFF:
        raise MigrationError("FwMark must fit in an unsigned 32-bit integer")
    if not 0 <= keepalive <= 65535:
        raise MigrationError("PersistentKeepalive must be between 0 and 65535")

    return ExistingGateway(
        interface=interface,
        server_address=str(server_interface),
        listen_port=listen_port,
        private_key=validate_key(private_key, "server private key"),
        fwmark=fwmark,
        client_address=str(client_interface),
        client_public_key=validate_key(
            str(one("Peer", "PublicKey")), "client public key"
        ),
        persistent_keepalive=keepalive,
        legacy_hooks=tuple(legacy_hooks),
    )


def parse_dns(value: str) -> tuple[str, ...]:
    items = tuple(item.strip() for item in value.split(","))
    if not items or any(not item for item in items):
        raise MigrationError("DNS upstreams must be comma-separated IP addresses")
    try:
        return tuple(str(ipaddress.ip_address(item)) for item in items)
    except ValueError as exc:
        raise MigrationError(f"invalid DNS upstream: {exc}") from exc


def discover_dns(root: Path) -> tuple[str, ...]:
    candidates = [rooted(root, "/etc/dnsmasq.conf")]
    directory = rooted(root, "/etc/dnsmasq.d")
    if directory.is_dir():
        candidates.extend(sorted(directory.glob("*.conf")))
    found: list[str] = []
    for path in candidates:
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise MigrationError(f"cannot read dnsmasq configuration {path}: {exc}") from exc
        for raw_line in lines:
            line = raw_line.strip()
            if line.startswith("server="):
                value = line.removeprefix("server=").split("#", 1)[0].strip()
                try:
                    address = str(ipaddress.ip_address(value))
                except ValueError:
                    continue
                if address not in found:
                    found.append(address)
    if not found:
        raise MigrationError(
            "no literal DNS upstreams were discovered; provide --dns-upstreams"
        )
    return tuple(found)


def atomic_write(path: Path, content: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def backup_files(root: Path, backup: Path, interface: str) -> dict[str, Any]:
    backup.mkdir(parents=True)
    os.chmod(backup, 0o700)
    entries: list[dict[str, Any]] = []
    for template in MANAGED_PATHS:
        absolute = template.format(interface=interface)
        source = rooted(root, absolute)
        entry: dict[str, Any] = {"path": absolute, "existed": source.exists()}
        if source.exists():
            if not source.is_file():
                raise MigrationError(f"backup source is not a regular file: {source}")
            relative = absolute.removeprefix("/")
            destination = backup / "files" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            os.chmod(destination, 0o600)
            data = destination.read_bytes()
            entry.update(
                {
                    "backup": f"files/{relative}",
                    "mode": source.stat().st_mode & 0o7777,
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
        entries.append(entry)

    if root == Path("/") and shutil.which("iptables-save"):
        result = subprocess.run(  # noqa: S603, S607 - fixed command
            ["iptables-save"], check=True, capture_output=True
        )
        atomic_write(backup / "iptables-save", result.stdout, 0o600)

    manifest = {
        "format": 1,
        "created_utc": datetime.now(UTC).isoformat(),
        "root": str(root),
        "tunnel_interface": interface,
        "files": entries,
    }
    atomic_write(
        backup / MANIFEST_NAME,
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(),
        0o600,
    )
    return manifest


def restore_files(root: Path, backup: Path) -> None:
    try:
        manifest = json.loads((backup / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationError(f"cannot read migration manifest: {exc}") from exc
    if manifest.get("format") != 1 or not isinstance(manifest.get("files"), list):
        raise MigrationError("unsupported or invalid migration manifest")
    for entry in manifest["files"]:
        absolute = entry.get("path")
        if not isinstance(absolute, str) or not absolute.startswith("/"):
            raise MigrationError("migration manifest contains an unsafe path")
        destination = rooted(root, absolute)
        if entry.get("existed"):
            relative = entry.get("backup")
            if not isinstance(relative, str) or Path(relative).is_absolute():
                raise MigrationError("migration manifest contains an unsafe backup path")
            source = backup / relative
            data = source.read_bytes()
            if hashlib.sha256(data).hexdigest() != entry.get("sha256"):
                raise MigrationError(f"backup checksum failed for {absolute}")
            atomic_write(destination, data, int(entry["mode"]))
            print(f"RESTORED: {destination}")
        elif destination.exists():
            if not destination.is_file():
                raise MigrationError(f"refusing to remove non-file path {destination}")
            destination.unlink()
            print(f"REMOVED: {destination}")


def setup_document(
    gateway: ExistingGateway, egress: str, dns: tuple[str, ...], client_key_path: str
) -> str:
    return (
        "# Generated by scripts/snarkypuss-migrate.py from the existing gateway.\n"
        "[gateway]\n"
        f"tunnel_interface = {gateway.interface}\n"
        f"server_address = {gateway.server_address}\n"
        f"listen_port = {gateway.listen_port}\n"
        f"client_address = {gateway.client_address}\n"
        f"client_public_key_file = {client_key_path}\n"
        f"persistent_keepalive = {gateway.persistent_keepalive}\n"
        f"dns_upstreams = {', '.join(dns)}\n"
        f"protected_egress_interface = {egress}\n"
        f"tunnel_fwmark = {gateway.fwmark:#x}\n"
    )


def audit(gateway: ExistingGateway, egress: str, dns: tuple[str, ...]) -> None:
    print("Snarkypuss existing-gateway migration audit")
    print(f"Tunnel interface: {gateway.interface}")
    print(f"Server address: {gateway.server_address}")
    print(f"Listen port: {gateway.listen_port}")
    print(f"Client address: {gateway.client_address}")
    print(f"Client public key: {gateway.client_public_key}")
    print(f"Persistent keepalive: {gateway.persistent_keepalive}")
    print(f"Tunnel firewall mark: {gateway.fwmark:#x}")
    print(f"Protected egress assertion: {egress}")
    print(f"DNS upstreams: {', '.join(dns)}")
    print("Server private key: present and valid (value intentionally not displayed)")
    if gateway.legacy_hooks:
        print(f"Legacy WireGuard lifecycle hooks found: {', '.join(gateway.legacy_hooks)}")
        print("They will not be copied into the generated managed configuration.")
    else:
        print("Legacy WireGuard lifecycle hooks found: none")


def main() -> int:
    arguments = parser().parse_args()
    root = arguments.root.resolve()
    if (arguments.prepare or arguments.restore) and root == Path("/") and os.geteuid() != 0:
        print("ERROR: file-changing migration modes must run as root.", file=sys.stderr)
        return 1
    try:
        if arguments.restore:
            backup = arguments.restore.resolve()
            restore_files(root, backup)
            print("File restoration complete. Live services and networking were not changed.")
            return 0

        interface = validate_interface(arguments.tunnel_interface, "tunnel interface")
        if not arguments.protected_egress_interface:
            raise MigrationError("--protected-egress-interface is required")
        egress = validate_interface(
            arguments.protected_egress_interface, "protected egress interface"
        )
        if egress == interface:
            raise MigrationError("protected egress must differ from the private tunnel")
        wireguard_path = rooted(root, f"/etc/wireguard/{interface}.conf")
        private_key_path = rooted(root, f"/etc/wireguard/{interface}.private.key")
        gateway = parse_wireguard(wireguard_path, interface, private_key_path)
        dns = (
            parse_dns(arguments.dns_upstreams)
            if arguments.dns_upstreams
            else discover_dns(root)
        )
        audit(gateway, egress, dns)
        if arguments.audit:
            print("Audit complete. No files, services, or network settings were changed.")
            return 0

        backup_parent = Path(arguments.backup_root)
        if not backup_parent.is_absolute():
            raise MigrationError("--backup-root must be an absolute path")
        backup_parent = rooted(root, str(backup_parent))
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup = backup_parent / f"migration-{timestamp}"
        counter = 1
        while backup.exists():
            backup = backup_parent / f"migration-{timestamp}-{counter}"
            counter += 1
        backup_files(root, backup, interface)
        print(f"BACKUP: {backup}")

        canonical_client_key_path = "/etc/snarkypuss/client.pub"
        client_key_path = (
            canonical_client_key_path
            if root == Path("/")
            else str(rooted(root, canonical_client_key_path))
        )
        setup_path = rooted(root, "/etc/snarkypuss-setup.conf")
        try:
            atomic_write(private_key_path, f"{gateway.private_key}\n".encode(), 0o600)
            atomic_write(
                rooted(root, canonical_client_key_path),
                f"{gateway.client_public_key}\n".encode(),
                0o600,
            )
            atomic_write(
                setup_path,
                setup_document(gateway, egress, dns, client_key_path).encode(),
                0o600,
            )
            configure = Path(__file__).with_name("snarkypuss-configure.py")
            result = subprocess.run(  # noqa: S603 - fixed sibling script
                [
                    sys.executable,
                    str(configure),
                    "--config",
                    str(setup_path),
                    "--root",
                    str(root),
                    "--apply",
                ],
                check=False,
            )
            if result.returncode != 0:
                raise MigrationError(
                    f"configuration generator exited with status {result.returncode}"
                )
        except (OSError, MigrationError) as exc:
            print(f"Preparation failed; restoring files from {backup}.", file=sys.stderr)
            restore_files(root, backup)
            raise MigrationError(str(exc)) from exc

        print("Migration preparation complete.")
        print("Live services, routes, firewall rules, and sysctl values were not changed.")
        print("Review the generated files, then use snarkypuss-activate.py for cutover.")
        print(f"File-only recovery: {Path(__file__).name} --restore {backup}")
        return 0
    except (MigrationError, OSError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

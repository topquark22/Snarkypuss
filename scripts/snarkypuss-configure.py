#!/usr/bin/env python3
"""Generate base Snarkypuss gateway configuration without activating it."""

from __future__ import annotations

import argparse
import base64
import binascii
import configparser
import ipaddress
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


ALLOWED_SECTION = "gateway"
ALLOWED_OPTIONS = {
    "tunnel_interface",
    "server_address",
    "listen_port",
    "client_address",
    "client_public_key_file",
    "dns_upstreams",
    "protected_egress_interface",
    "tunnel_fwmark",
}


class ConfigurationError(ValueError):
    """A setup value is absent, unsupported, or unsafe."""


@dataclass(frozen=True)
class GatewayConfig:
    tunnel_interface: str
    server_interface: ipaddress.IPv4Interface
    listen_port: int
    client_interface: ipaddress.IPv4Interface
    client_public_key: str
    dns_upstreams: tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]
    protected_egress_interface: str
    tunnel_fwmark: int


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description=(
            "Validate a non-secret setup file and generate inactive WireGuard, "
            "dnsmasq, and sysctl configuration."
        )
    )
    result.add_argument(
        "--config",
        required=True,
        type=Path,
        help="path to snarkypuss-setup.conf",
    )
    result.add_argument(
        "--root",
        type=Path,
        default=Path("/"),
        help="destination filesystem root (default: /; useful for staging tests)",
    )
    mode = result.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="validate and describe changes without writing anything",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="write configuration after validation",
    )
    return result


def validate_wireguard_key(value: str, label: str) -> str:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ConfigurationError(f"{label} is not valid base64") from exc
    if len(decoded) != 32 or len(value) != 44:
        raise ConfigurationError(f"{label} is not a 32-byte WireGuard key")
    return value


def read_setup(path: Path) -> GatewayConfig:
    document = configparser.ConfigParser(interpolation=None, strict=True)
    document.optionxform = str.lower
    try:
        with path.open(encoding="utf-8") as stream:
            document.read_file(stream)
    except (OSError, configparser.Error) as exc:
        raise ConfigurationError(f"cannot read setup file {path}: {exc}") from exc

    if document.defaults():
        raise ConfigurationError("setup file may not contain a [DEFAULT] section")
    if set(document.sections()) != {ALLOWED_SECTION}:
        raise ConfigurationError(
            f"setup file must contain exactly one [{ALLOWED_SECTION}] section"
        )
    section = document[ALLOWED_SECTION]
    unknown = set(section) - ALLOWED_OPTIONS
    missing = ALLOWED_OPTIONS - set(section)
    if unknown:
        raise ConfigurationError(f"unknown setup option(s): {', '.join(sorted(unknown))}")
    if missing:
        raise ConfigurationError(f"missing setup option(s): {', '.join(sorted(missing))}")

    interface = section["tunnel_interface"].strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,15}", interface):
        raise ConfigurationError("tunnel_interface is not a valid Linux interface name")
    egress_interface = section["protected_egress_interface"].strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,15}", egress_interface):
        raise ConfigurationError(
            "protected_egress_interface is not a valid Linux interface name"
        )
    if egress_interface == interface:
        raise ConfigurationError(
            "protected_egress_interface must differ from tunnel_interface"
        )
    raw_fwmark = section["tunnel_fwmark"].strip()
    try:
        tunnel_fwmark = int(raw_fwmark, 0)
    except ValueError as exc:
        raise ConfigurationError("tunnel_fwmark must be a decimal or 0x-prefixed integer") from exc
    if not 0 <= tunnel_fwmark <= 0xFFFFFFFF:
        raise ConfigurationError("tunnel_fwmark must fit in an unsigned 32-bit integer")

    try:
        server = ipaddress.IPv4Interface(section["server_address"].strip())
        client = ipaddress.IPv4Interface(section["client_address"].strip())
    except ValueError as exc:
        raise ConfigurationError(f"invalid IPv4 interface address: {exc}") from exc
    if client.ip not in server.network:
        raise ConfigurationError("client_address must belong to the server_address network")
    if client.ip == server.ip:
        raise ConfigurationError("client_address must differ from server_address")

    try:
        listen_port = int(section["listen_port"])
    except ValueError as exc:
        raise ConfigurationError("listen_port must be an integer") from exc
    if not 1 <= listen_port <= 65535:
        raise ConfigurationError("listen_port must be between 1 and 65535")

    key_path = Path(section["client_public_key_file"].strip())
    if not key_path.is_absolute():
        raise ConfigurationError("client_public_key_file must be an absolute path")
    try:
        client_key = key_path.read_text(encoding="ascii").strip()
    except OSError as exc:
        raise ConfigurationError(f"cannot read client public key file {key_path}: {exc}") from exc
    validate_wireguard_key(client_key, "client public key")

    raw_dns = [item.strip() for item in section["dns_upstreams"].split(",")]
    if not raw_dns or any(not item for item in raw_dns):
        raise ConfigurationError("dns_upstreams must contain comma-separated IP addresses")
    try:
        dns = tuple(ipaddress.ip_address(item) for item in raw_dns)
    except ValueError as exc:
        raise ConfigurationError(f"invalid DNS upstream address: {exc}") from exc

    return GatewayConfig(
        tunnel_interface=interface,
        server_interface=server,
        listen_port=listen_port,
        client_interface=client,
        client_public_key=client_key,
        dns_upstreams=dns,
        protected_egress_interface=egress_interface,
        tunnel_fwmark=tunnel_fwmark,
    )


def rooted(root: Path, absolute_path: str) -> Path:
    return root / absolute_path.removeprefix("/")


def read_private_key(path: Path) -> str:
    try:
        value = path.read_text(encoding="ascii").strip()
    except OSError as exc:
        raise ConfigurationError(f"cannot read existing server private key {path}: {exc}") from exc
    return validate_wireguard_key(value, "existing server private key")


def generate_private_key() -> str:
    try:
        result = subprocess.run(  # noqa: S603, S607 - fixed reviewed command
            ["wg", "genkey"],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise ConfigurationError("wg is required to generate the server private key") from exc
    except subprocess.CalledProcessError as exc:
        raise ConfigurationError(f"wg genkey failed: {exc.stderr.strip()}") from exc
    return validate_wireguard_key(result.stdout.strip(), "generated server private key")


def render_wireguard(config: GatewayConfig, private_key: str) -> str:
    return (
        "# Generated by scripts/snarkypuss-configure.py; do not add firewall commands here.\n"
        "[Interface]\n"
        f"Address = {config.server_interface}\n"
        f"ListenPort = {config.listen_port}\n"
        f"PrivateKey = {private_key}\n"
        f"FwMark = {config.tunnel_fwmark:#x}\n"
        "SaveConfig = false\n"
        "\n"
        "[Peer]\n"
        f"PublicKey = {config.client_public_key}\n"
        f"AllowedIPs = {config.client_interface}\n"
    )


def render_dnsmasq(config: GatewayConfig) -> str:
    servers = "".join(f"server={address}\n" for address in config.dns_upstreams)
    return (
        "# Generated by scripts/snarkypuss-configure.py\n"
        f"interface={config.tunnel_interface}\n"
        "bind-interfaces\n"
        f"listen-address={config.server_interface.ip}\n"
        "domain-needed\n"
        "bogus-priv\n"
        f"{servers}"
    )


def backup_path(path: Path, timestamp: str) -> Path:
    candidate = path.with_name(f"{path.name}.bak.{timestamp}")
    counter = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.bak.{timestamp}.{counter}")
        counter += 1
    return candidate


def atomic_write(path: Path, content: str, mode: int, timestamp: str) -> str:
    encoded = content.encode()
    if path.exists() and path.read_bytes() == encoded:
        os.chmod(path, mode)
        return "unchanged"

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = backup_path(path, timestamp)
        shutil.copy2(path, backup)
        os.chmod(backup, mode)
        print(f"BACKUP: {path} -> {backup}")

    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return "written"


def public_key(private_key: str) -> str:
    try:
        result = subprocess.run(  # noqa: S603, S607 - fixed reviewed command
            ["wg", "pubkey"],
            input=f"{private_key}\n",
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise ConfigurationError("wg pubkey failed while deriving the server public key") from exc
    return validate_wireguard_key(result.stdout.strip(), "derived server public key")


def main() -> int:
    arguments = parser().parse_args()
    config_path = arguments.config.resolve()
    root = arguments.root.resolve()

    if arguments.apply and root == Path("/") and os.geteuid() != 0:
        print("ERROR: --apply to / must run as root, for example with sudo.", file=sys.stderr)
        return 1

    try:
        config = read_setup(config_path)
        private_key_path = rooted(
            root, f"/etc/wireguard/{config.tunnel_interface}.private.key"
        )
        wireguard_path = rooted(root, f"/etc/wireguard/{config.tunnel_interface}.conf")
        dnsmasq_path = rooted(root, "/etc/dnsmasq.d/snarkypuss.conf")
        sysctl_path = rooted(root, "/etc/sysctl.d/90-snarkypuss.conf")

        if wireguard_path.exists() and not private_key_path.exists():
            raise ConfigurationError(
                f"{wireguard_path} exists but {private_key_path} does not; "
                "refusing to rotate an unknown server key"
            )

        existing_key = private_key_path.exists()
        if existing_key:
            private_key = read_private_key(private_key_path)
        elif arguments.dry_run:
            private_key = "DRY_RUN_PRIVATE_KEY_PLACEHOLDER"
        else:
            private_key = generate_private_key()
        server_public_key = None if arguments.dry_run else public_key(private_key)

        targets = (
            (private_key_path, "server private key", 0o600),
            (wireguard_path, "WireGuard configuration", 0o600),
            (dnsmasq_path, "dnsmasq configuration", 0o644),
            (sysctl_path, "IPv4 forwarding configuration", 0o644),
        )

        print("Snarkypuss configuration generation")
        print(f"Mode: {'apply' if arguments.apply else 'dry-run'}")
        print(f"Destination root: {root}")
        for path, label, _mode in targets:
            action = "preserve" if label == "server private key" and existing_key else "generate"
            if path.exists() and label != "server private key":
                action = "compare, back up if changed, and replace"
            print(f"PLAN: {action} {label}: {path}")

        if arguments.dry_run:
            print("No files were written and no services or network settings were changed.")
            return 0

        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        private_key_path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(private_key_path.parent, 0o700)
        if not existing_key:
            result = atomic_write(private_key_path, f"{private_key}\n", 0o600, timestamp)
            print(f"{result.upper()}: {private_key_path}")

        wireguard_result = atomic_write(
            wireguard_path,
            render_wireguard(config, private_key),
            0o600,
            timestamp,
        )
        dnsmasq_result = atomic_write(
            dnsmasq_path,
            render_dnsmasq(config),
            0o644,
            timestamp,
        )
        sysctl_result = atomic_write(
            sysctl_path,
            "# Generated by scripts/snarkypuss-configure.py\nnet.ipv4.ip_forward=1\n",
            0o644,
            timestamp,
        )
        print(f"{wireguard_result.upper()}: {wireguard_path}")
        print(f"{dnsmasq_result.upper()}: {dnsmasq_path}")
        print(f"{sysctl_result.upper()}: {sysctl_path}")
        print(f"Server WireGuard public key: {server_public_key}")
        print(
            "Configuration was generated but not activated. No service, route, "
            "firewall rule, or sysctl value was changed."
        )
        return 0
    except ConfigurationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

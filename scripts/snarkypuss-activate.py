#!/usr/bin/env python3
"""Transactionally activate generated Snarkypuss gateway configuration."""

from __future__ import annotations

import argparse
import configparser
import fcntl
import ipaddress
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


STATE_DIRECTORY = Path("/var/lib/snarkypuss/activations")
PERSISTENT_RULES = Path("/etc/iptables/rules.v4")
FORWARD_CHAIN = "SNARKYPUSS_FORWARD"
NAT_CHAIN = "SNARKYPUSS_NAT"


class ActivationError(RuntimeError):
    """Activation input or an external operation failed safely."""


def run(
    command: list[str],
    *,
    check: bool = True,
    capture: bool = False,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(  # noqa: S603 - fixed reviewed commands
            command,
            check=check,
            capture_output=capture,
            input=input_text,
            text=True,
        )
    except FileNotFoundError as exc:
        raise ActivationError(f"required command is unavailable: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise ActivationError(f"{' '.join(command)} failed: {detail}") from exc


def read_activation_config(path: Path) -> dict[str, str]:
    document = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        with path.open(encoding="utf-8") as stream:
            document.read_file(stream)
    except (OSError, configparser.Error) as exc:
        raise ActivationError(f"cannot read setup file {path}: {exc}") from exc
    if set(document.sections()) != {"gateway"}:
        raise ActivationError("setup file must contain exactly one [gateway] section")
    section = document["gateway"]
    required = {
        "tunnel_interface",
        "server_address",
        "client_address",
        "protected_egress_interface",
        "tunnel_fwmark",
    }
    allowed = {
        "tunnel_interface",
        "server_address",
        "listen_port",
        "client_address",
        "client_public_key_file",
        "dns_upstreams",
        "protected_egress_interface",
        "tunnel_fwmark",
    }
    unknown = set(section) - allowed
    if unknown:
        raise ActivationError(f"unknown setup option(s): {', '.join(sorted(unknown))}")
    missing = required - set(section)
    if missing:
        raise ActivationError(f"missing setup option(s): {', '.join(sorted(missing))}")

    tunnel = section["tunnel_interface"].strip()
    egress = section["protected_egress_interface"].strip()
    for label, value in (("tunnel_interface", tunnel), ("protected_egress_interface", egress)):
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,15}", value):
            raise ActivationError(f"{label} is not a valid Linux interface name")
    if tunnel == egress:
        raise ActivationError("protected egress must differ from the private tunnel")

    try:
        server = ipaddress.IPv4Interface(section["server_address"].strip())
        client = ipaddress.IPv4Interface(section["client_address"].strip())
    except ValueError as exc:
        raise ActivationError(f"invalid tunnel address: {exc}") from exc
    if client.ip not in server.network:
        raise ActivationError("client address is outside the server tunnel network")
    return {
        "tunnel_interface": tunnel,
        "protected_egress_interface": egress,
        "client_cidr": str(server.network),
    }


def output(command: list[str]) -> str:
    return run(command, capture=True).stdout


def service_state(unit: str) -> dict[str, str | bool]:
    active = run(["systemctl", "is-active", "--quiet", unit], check=False).returncode == 0
    enabled = run(["systemctl", "is-enabled", "--quiet", unit], check=False).returncode == 0
    return {"unit": unit, "active": active, "enabled": enabled}


def write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(state, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def remove_owned_firewall() -> None:
    while run(
        ["iptables", "-C", "FORWARD", "-j", FORWARD_CHAIN], check=False
    ).returncode == 0:
        run(["iptables", "-D", "FORWARD", "-j", FORWARD_CHAIN])
    run(["iptables", "-F", FORWARD_CHAIN], check=False)
    run(["iptables", "-X", FORWARD_CHAIN], check=False)

    while run(
        ["iptables", "-t", "nat", "-C", "POSTROUTING", "-j", NAT_CHAIN],
        check=False,
    ).returncode == 0:
        run(["iptables", "-t", "nat", "-D", "POSTROUTING", "-j", NAT_CHAIN])
    run(["iptables", "-t", "nat", "-F", NAT_CHAIN], check=False)
    run(["iptables", "-t", "nat", "-X", NAT_CHAIN], check=False)


def apply_firewall(config: dict[str, str]) -> None:
    tunnel = config["tunnel_interface"]
    client_cidr = config["client_cidr"]
    remove_owned_firewall()

    run(["iptables", "-N", FORWARD_CHAIN])
    run(
        [
            "iptables",
            "-A",
            FORWARD_CHAIN,
            "-m",
            "conntrack",
            "--ctstate",
            "ESTABLISHED,RELATED",
            "-j",
            "ACCEPT",
        ]
    )
    run(
        [
            "iptables",
            "-A",
            FORWARD_CHAIN,
            "-i",
            tunnel,
            "-s",
            client_cidr,
            "-j",
            "ACCEPT",
        ]
    )
    run(["iptables", "-A", FORWARD_CHAIN, "-j", "RETURN"])
    run(["iptables", "-I", "FORWARD", "1", "-j", FORWARD_CHAIN])

    run(["iptables", "-t", "nat", "-N", NAT_CHAIN])
    run(
        [
            "iptables",
            "-t",
            "nat",
            "-A",
            NAT_CHAIN,
            "-s",
            client_cidr,
            "-j",
            "MASQUERADE",
        ]
    )
    run(["iptables", "-t", "nat", "-A", NAT_CHAIN, "-j", "RETURN"])
    run(["iptables", "-t", "nat", "-I", "POSTROUTING", "1", "-j", NAT_CHAIN])


def firewall_plan(config: dict[str, str]) -> str:
    return "\n".join(
        (
            f"Require protected provider interface "
            f"{config['protected_egress_interface']} to exist at activation.",
            f"Forward {config['client_cidr']} arriving from "
            f"{config['tunnel_interface']} according to provider-managed routing.",
            "Accept established and related return traffic.",
            "Masquerade the client network on whichever egress the provider selects.",
            "Do not alter INPUT, OUTPUT, provider routes, or provider firewall settings.",
        )
    )


def confirm(token: str) -> int:
    if not re.fullmatch(r"[0-9a-f]{16}", token):
        raise ActivationError("activation token must contain 16 lowercase hexadecimal digits")
    path = STATE_DIRECTORY / f"{token}.json"
    if not path.is_file():
        raise ActivationError(f"activation token does not exist: {token}")
    lock_path = path.with_suffix(".lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = json.loads(path.read_text(encoding="utf-8"))
        if state["status"] != "pending":
            raise ActivationError(f"activation status is already {state['status']}")
        run(["netfilter-persistent", "save"])
        run(["systemctl", "stop", f"snarkypuss-rollback-{token}.timer"], check=False)
        state["status"] = "confirmed"
        write_state(path, state)
    print(f"Confirmed Snarkypuss activation {token}; firewall rules are now persistent.")
    return 0


def apply(arguments: argparse.Namespace, config: dict[str, str]) -> int:
    if os.geteuid() != 0:
        raise ActivationError("--apply must run as root")
    if not arguments.console_confirmed:
        raise ActivationError(
            "--apply requires --console-confirmed after verifying VPS console access"
        )
    if not arguments.provider_leak_protection_confirmed:
        raise ActivationError(
            "--apply requires --provider-leak-protection-confirmed after verifying "
            "the provider kill switch or equivalent policy"
        )
    if not 30 <= arguments.rollback_after <= 600:
        raise ActivationError("--rollback-after must be between 30 and 600 seconds")

    tunnel = config["tunnel_interface"]
    egress = config["protected_egress_interface"]
    wireguard_config = Path(f"/etc/wireguard/{tunnel}.conf")
    if not wireguard_config.is_file():
        raise ActivationError(f"generated WireGuard configuration is missing: {wireguard_config}")
    if not Path("/etc/dnsmasq.d/snarkypuss.conf").is_file():
        raise ActivationError("generated dnsmasq configuration is missing")
    run(["ip", "link", "show", "dev", egress], capture=True)
    run(["wg-quick", "strip", tunnel], capture=True)
    run(["dnsmasq", "--test"], capture=True)

    token = secrets.token_hex(8)
    state_path = STATE_DIRECTORY / f"{token}.json"
    rollback_script = Path(__file__).with_name("snarkypuss-rollback.py").resolve()
    if not rollback_script.is_file():
        raise ActivationError(f"rollback script is missing: {rollback_script}")
    persistent = PERSISTENT_RULES.read_text(encoding="utf-8") if PERSISTENT_RULES.exists() else ""
    services = [
        service_state(f"wg-quick@{tunnel}.service"),
        service_state("dnsmasq.service"),
    ]
    state: dict[str, Any] = {
        "token": token,
        "status": "pending",
        "iptables_save": output(["iptables-save"]),
        "ip_forward": output(["sysctl", "-n", "net.ipv4.ip_forward"]).strip(),
        "services": services,
        "persistent_rules_path": str(PERSISTENT_RULES),
        "persistent_rules_existed": PERSISTENT_RULES.exists(),
        "persistent_rules": persistent,
    }
    write_state(state_path, state)

    unit = f"snarkypuss-rollback-{token}"
    run(
        [
            "systemd-run",
            "--quiet",
            "--collect",
            "--unit",
            unit,
            f"--on-active={arguments.rollback_after}s",
            "--timer-property=AccuracySec=1s",
            "/usr/bin/python3",
            str(rollback_script),
            "--state",
            str(state_path),
            "--automatic",
        ]
    )

    try:
        apply_firewall(config)
        run(["sysctl", "-w", "net.ipv4.ip_forward=1"])
        run(["systemctl", "enable", "--now", f"wg-quick@{tunnel}.service"])
        run(["systemctl", "enable", "--now", "dnsmasq.service"])
    except ActivationError:
        run(
            [
                "/usr/bin/python3",
                str(rollback_script),
                "--state",
                str(state_path),
                "--force",
            ],
            check=False,
        )
        raise

    print(f"Activation token: {token}")
    print(f"Automatic rollback is scheduled in {arguments.rollback_after} seconds.")
    print("Verify private-tunnel access and egress now, then confirm with:")
    print(f"  sudo scripts/snarkypuss-activate.py --confirm {token}")
    print("If confirmation is not received, the previous state will be restored.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Activate generated Snarkypuss configuration.")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--dry-run", action="store_true", help="validate and print the plan")
    action.add_argument("--apply", action="store_true", help="activate with timed rollback")
    action.add_argument("--confirm", metavar="TOKEN", help="confirm and persist an activation")
    parser.add_argument("--config", type=Path, help="path to snarkypuss-setup.conf")
    parser.add_argument(
        "--rollback-after",
        type=int,
        default=120,
        help="rollback timeout in seconds",
    )
    parser.add_argument(
        "--console-confirmed",
        action="store_true",
        help="assert that independent VPS console access works",
    )
    parser.add_argument(
        "--provider-leak-protection-confirmed",
        action="store_true",
        help="assert that provider fail-closed or kill-switch policy is configured",
    )
    arguments = parser.parse_args()
    try:
        if arguments.confirm:
            if os.geteuid() != 0:
                raise ActivationError("--confirm must run as root")
            return confirm(arguments.confirm)
        if arguments.config is None:
            raise ActivationError("--config is required with --dry-run or --apply")
        config = read_activation_config(arguments.config.resolve())
        print("Snarkypuss activation plan")
        print(firewall_plan(config))
        if arguments.dry_run:
            print("No service, sysctl value, route, or firewall rule was changed.")
            return 0
        return apply(arguments, config)
    except (ActivationError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Restore gateway state captured by snarkypuss-activate.py."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


STATE_DIRECTORY = Path("/var/lib/snarkypuss/activations")


def run(command: list[str], *, input_text: str | None = None, check: bool = True) -> None:
    subprocess.run(  # noqa: S603 - fixed commands and captured activation state
        command,
        input=input_text,
        check=check,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def write_state(path: Path, state: dict[str, Any]) -> None:
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


def restore_service(unit: str, was_enabled: bool, was_active: bool) -> None:
    run(["systemctl", "enable" if was_enabled else "disable", unit], check=False)
    run(["systemctl", "start" if was_active else "stop", unit], check=False)


def state_path(arguments: argparse.Namespace) -> Path:
    if arguments.state is not None:
        return arguments.state.resolve()
    if not re.fullmatch(r"[0-9a-f]{16}", arguments.token):
        raise ValueError("activation token must contain 16 lowercase hexadecimal digits")
    return STATE_DIRECTORY / f"{arguments.token}.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Roll back a Snarkypuss activation.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--token", help="activation token")
    source.add_argument("--state", type=Path, help=argparse.SUPPRESS)
    parser.add_argument(
        "--force",
        action="store_true",
        help="roll back even after the activation was confirmed",
    )
    parser.add_argument("--automatic", action="store_true", help=argparse.SUPPRESS)
    arguments = parser.parse_args()

    if os.geteuid() != 0:
        print("ERROR: rollback must run as root.", file=sys.stderr)
        return 1

    try:
        path = state_path(arguments)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if not path.is_file():
        print(f"ERROR: activation state does not exist: {path}", file=sys.stderr)
        return 1

    lock_path = path.with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"ERROR: cannot read activation state: {exc}", file=sys.stderr)
            return 1
        status = state.get("status")
        if status == "rolled_back":
            print(f"Activation {state['token']} was already rolled back.")
            return 0
        if status == "confirmed" and not arguments.force:
            if not arguments.automatic:
                print("ERROR: confirmed activation requires --force to roll back.", file=sys.stderr)
                return 1
            return 0

        try:
            run(["iptables-restore"], input_text=state["iptables_save"])
            run(["sysctl", "-w", f"net.ipv4.ip_forward={state['ip_forward']}"])
            for service in state["services"]:
                restore_service(
                    service["unit"],
                    service["enabled"],
                    service["active"],
                )

            if status == "confirmed":
                persistent_path = Path(state["persistent_rules_path"])
                if state["persistent_rules_existed"]:
                    persistent_path.parent.mkdir(parents=True, exist_ok=True)
                    persistent_path.write_text(
                        state["persistent_rules"],
                        encoding="utf-8",
                    )
                    os.chmod(persistent_path, 0o600)
                else:
                    persistent_path.unlink(missing_ok=True)

            state["status"] = "rolled_back"
            write_state(path, state)
            timer = f"snarkypuss-rollback-{state['token']}.timer"
            run(["systemctl", "stop", timer], check=False)
            print(f"Rolled back Snarkypuss activation {state['token']}.")
            if status == "confirmed":
                print(
                    "The complete saved firewall snapshot was restored; firewall "
                    "changes made after activation were discarded."
                )
            return 0
        except (KeyError, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
            print(f"ERROR: rollback failed: {exc}", file=sys.stderr)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())

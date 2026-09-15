"""Tests for the Snarkypuss NordVPN setup helper."""

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest


SCRIPT = Path("scripts/snarkypuss-nordvpn-configure.py")
GUIDE = Path("docs/07_NORDVPN.md")


def load_module() -> Any:
    spec = importlib.util.spec_from_file_location("snarkypuss_nordvpn_setup_test", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_config(tmp_path: Path) -> Path:
    path = tmp_path / "setup.conf"
    path.write_text(
        "\n".join(
            (
                "[gateway]",
                "server_address = 10.8.0.1/24",
                "listen_port = 51820",
                "",
            )
        ),
        encoding="utf-8",
    )
    return path


def test_policy_is_derived_from_gateway_config(tmp_path: Path) -> None:
    module = load_module()
    policy = module.read_gateway_policy(write_config(tmp_path))

    assert policy.listen_port == 51820
    assert str(policy.management_subnet) == "10.8.0.0/24"


def test_detects_current_allowlist_command() -> None:
    module = load_module()

    def runner(arguments: tuple[str, ...]) -> Any:
        if arguments == ("help",):
            return module.CommandResult(0, "Commands: allowlist connect settings\n", "")
        raise AssertionError(arguments)

    assert module.detect_allowlist_command(runner) == "allowlist"


def test_detects_legacy_whitelist_command() -> None:
    module = load_module()

    def runner(arguments: tuple[str, ...]) -> Any:
        if arguments == ("help",):
            return module.CommandResult(0, "Commands: whitelist connect settings\n", "")
        raise AssertionError(arguments)

    assert module.detect_allowlist_command(runner) == "whitelist"


def test_current_plan_uses_udp_port_and_management_subnet(tmp_path: Path) -> None:
    module = load_module()
    policy = module.read_gateway_policy(write_config(tmp_path))

    commands = module.plan(policy, "allowlist")

    assert ("allowlist", "add", "port", "51820", "protocol", "UDP") in commands
    assert ("allowlist", "add", "subnet", "10.8.0.0/24") in commands
    assert commands[-1] == ("set", "killswitch", "on")


def test_apply_orders_exceptions_before_killswitch(tmp_path: Path) -> None:
    module = load_module()
    policy = module.read_gateway_policy(write_config(tmp_path))
    events: list[tuple[str, ...]] = []

    def runner(arguments: tuple[str, ...]) -> Any:
        events.append(tuple(arguments))
        if arguments == ("help",):
            return module.CommandResult(0, "allowlist\n", "")
        if arguments == ("settings",):
            return module.CommandResult(
                0,
                "Technology: NordLynx\nKill Switch: enabled\nAuto-connect: disabled\n",
                "",
            )
        return module.CommandResult(0, "", "")

    module.apply_policy(policy, runner)

    assert events.index(("allowlist", "add", "port", "51820", "protocol", "UDP")) < events.index(
        ("set", "killswitch", "on")
    )
    assert events.index(("allowlist", "add", "subnet", "10.8.0.0/24")) < events.index(
        ("set", "killswitch", "on")
    )


def test_apply_tolerates_existing_exception(tmp_path: Path) -> None:
    module = load_module()
    policy = module.read_gateway_policy(write_config(tmp_path))

    def runner(arguments: tuple[str, ...]) -> Any:
        if arguments == ("help",):
            return module.CommandResult(0, "allowlist\n", "")
        if arguments and arguments[0] == "allowlist":
            return module.CommandResult(1, "", "Entry already exists in allowlist")
        if arguments == ("settings",):
            return module.CommandResult(
                0,
                "Technology: NordLynx\nKill Switch: enabled\nAuto-connect: disabled\n",
                "",
            )
        return module.CommandResult(0, "", "")

    module.apply_policy(policy, runner)


def test_settings_verification_rejects_unsafe_state() -> None:
    module = load_module()

    with pytest.raises(module.NordVpnSetupError, match="Kill Switch"):
        module.verify_settings(
            "Technology: NordLynx\nKill Switch: disabled\nAuto-connect: disabled\n"
        )


def test_apply_requires_console_confirmation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_module()
    config = write_config(tmp_path)

    monkeypatch.setattr(module, "detect_allowlist_command", lambda _runner: "allowlist")
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)

    result = module.main(["--config", str(config), "--apply"])

    assert result == 1


def test_nordvpn_guide_invokes_setup_helper() -> None:
    guide = GUIDE.read_text(encoding="utf-8")

    assert "scripts/snarkypuss-nordvpn-configure.py" in guide
    assert "--dry-run" in guide
    assert "--apply" in guide
    assert "--console-confirmed" in guide
    assert "fail-closed" in guide.casefold()

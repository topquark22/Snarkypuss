"""Tests for the provider-neutral upstream VPN boundary."""

import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from snarkyctl.providers import (
    ProviderError,
    VpnState,
    VpnTarget,
    available_providers,
    create_provider,
)
from snarkyctl.providers.nordvpn import (
    MAX_OUTPUT_LENGTH,
    CommandResult,
    NordVpnProvider,
    parse_settings,
    parse_status,
    run_command,
)
from snarkyctl.providers.placeholder import PlaceholderProvider


def target() -> VpnTarget:
    return VpnTarget(alias="dallas", label="Dallas, United States", provider_target="us9167")


def test_registry_contains_only_compiled_provider_names() -> None:
    assert available_providers() == ("nordvpn",)
    assert isinstance(create_provider("nordvpn"), NordVpnProvider)


def test_registry_rejects_arbitrary_module_name() -> None:
    with pytest.raises(ProviderError) as error:
        create_provider("some.user.module")

    assert error.value.code == "UNKNOWN_PROVIDER"


CONNECTED_STATUS = """Status: Connected
Server: United States #6275
Hostname: us6275.nordvpn.com
IP: 107.175.104.227
Country: United States
City: Chicago
Current technology: NORDLYNX
Current protocol: UDP
Post-quantum VPN: Disabled
Transfer: 1 MiB received, 2 KiB sent
Uptime: 1 minute 2 seconds
"""


def test_parse_connected_nordvpn_status() -> None:
    status = parse_status(CONNECTED_STATUS)
    assert status.state is VpnState.CONNECTED
    assert status.provider == "nordvpn"
    assert status.display_name == "United States #6275"
    assert status.interface == "nordlynx"
    assert status.details["hostname"] == "us6275.nordvpn.com"


def test_parse_disconnected_nordvpn_status() -> None:
    status = parse_status("Status: Disconnected\n")
    assert status.state is VpnState.DISCONNECTED
    assert status.interface is None


def test_parse_nordvpn_settings() -> None:
    settings = parse_settings(
        """Technology: NORDLYNX
Firewall: enabled
Firewall Mark: 0xe1f1
Routing: enabled
Kill Switch: enabled
"""
    )
    assert settings.leak_protection_enabled is True
    assert settings.firewall_enabled is True
    assert settings.routing_enabled is True
    assert settings.firewall_mark == "0xe1f1"


def test_parse_disabled_nordvpn_kill_switch() -> None:
    settings = parse_settings("Kill Switch: disabled\nFirewall: enabled\n")
    assert settings.leak_protection_enabled is False


def test_parse_unknown_nordvpn_status_is_controlled_failure() -> None:
    with pytest.raises(ProviderError) as error:
        parse_status("Unexpected output\n")
    assert error.value.code == "UNPARSEABLE_STATUS"


def test_parse_nordvpn_status_rejects_oversized_field() -> None:
    with pytest.raises(ProviderError) as error:
        parse_status("Status: Connected\nServer: " + "x" * 257)
    assert error.value.code == "PROVIDER_OUTPUT_INVALID"


def test_nordvpn_status_invokes_fixed_command() -> None:
    calls: list[tuple[str, ...]] = []

    def runner(_executable: object, arguments: object, _timeout: float) -> CommandResult:
        args = tuple(arguments)  # type: ignore[arg-type]
        calls.append(args)
        return CommandResult(0, CONNECTED_STATUS, "")

    provider = NordVpnProvider(runner=runner)
    assert provider.status().state is VpnState.CONNECTED
    assert calls == [("status",)]


def test_nordvpn_settings_invokes_fixed_command() -> None:
    provider = NordVpnProvider(
        runner=lambda *_args: CommandResult(
            0, "Kill Switch: enabled\nFirewall: enabled\n", ""
        )
    )
    assert provider.settings().leak_protection_enabled is True


def test_nordvpn_connect_uses_one_configured_target_argument() -> None:
    calls: list[tuple[str, ...]] = []

    def runner(_executable: object, arguments: object, _timeout: float) -> CommandResult:
        args = tuple(arguments)  # type: ignore[arg-type]
        calls.append(args)
        output = CONNECTED_STATUS if args == ("status",) else "Connected\n"
        return CommandResult(0, output, "")

    status = NordVpnProvider(runner=runner).connect(target())
    assert calls == [("connect", "us9167"), ("status",)]
    assert status.target == "dallas"


def test_nordvpn_disconnect_then_reads_status() -> None:
    calls: list[tuple[str, ...]] = []

    def runner(_executable: object, arguments: object, _timeout: float) -> CommandResult:
        args = tuple(arguments)  # type: ignore[arg-type]
        calls.append(args)
        output = "Status: Disconnected\n" if args == ("status",) else "Disconnected\n"
        return CommandResult(0, output, "")

    status = NordVpnProvider(runner=runner).disconnect()
    assert status.state is VpnState.DISCONNECTED
    assert calls == [("disconnect",), ("status",)]


def test_nordvpn_rejects_option_like_target() -> None:
    invalid = VpnTarget(alias="bad", label="Bad", provider_target="--group Double_VPN")
    with pytest.raises(ProviderError) as error:
        NordVpnProvider(runner=lambda *_args: CommandResult(0, "", "")).connect(invalid)
    assert error.value.code == "INVALID_TARGET"


def test_nordvpn_command_failure_is_controlled() -> None:
    provider = NordVpnProvider(runner=lambda *_args: CommandResult(7, "", "failure"))
    with pytest.raises(ProviderError) as error:
        provider.status()
    assert error.value.code == "PROVIDER_COMMAND_FAILED"


def test_command_runner_uses_argument_array(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[list[str]] = []

    def fake_run(arguments: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, stdout="ok", stderr="")

    monkeypatch.setattr("snarkyctl.providers.nordvpn.subprocess.run", fake_run)
    result = run_command(Path("/usr/bin/nordvpn"), ("connect", "us9167"), 5)
    assert result.stdout == "ok"
    assert captured == [["/usr/bin/nordvpn", "connect", "us9167"]]


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (FileNotFoundError(), "PROVIDER_UNAVAILABLE"),
        (PermissionError(), "PROVIDER_PERMISSION_DENIED"),
        (subprocess.TimeoutExpired("nordvpn", 5), "PROVIDER_TIMEOUT"),
    ],
)
def test_command_runner_maps_operating_system_failures(
    monkeypatch: pytest.MonkeyPatch, failure: BaseException, code: str
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise failure

    monkeypatch.setattr("snarkyctl.providers.nordvpn.subprocess.run", fail)
    with pytest.raises(ProviderError) as error:
        run_command(Path("/usr/bin/nordvpn"), ("status",), 5)
    assert error.value.code == code


def test_command_runner_rejects_large_output(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 0, stdout="x" * (MAX_OUTPUT_LENGTH + 1), stderr="")

    monkeypatch.setattr("snarkyctl.providers.nordvpn.subprocess.run", fake_run)
    with pytest.raises(ProviderError) as error:
        run_command(Path("/usr/bin/nordvpn"), ("status",), 5)
    assert error.value.code == "PROVIDER_OUTPUT_TOO_LARGE"


def test_placeholder_reports_disconnected() -> None:
    provider = PlaceholderProvider()

    status = provider.status()

    assert status.state is VpnState.DISCONNECTED
    assert status.provider == "placeholder"
    assert provider.capabilities.connect is False


def test_placeholder_rejects_mutation() -> None:
    provider = PlaceholderProvider()

    with pytest.raises(ProviderError, match="cannot connect") as connect_error:
        provider.connect(target())
    with pytest.raises(ProviderError, match="cannot disconnect") as disconnect_error:
        provider.disconnect()

    assert connect_error.value.code == "UNSUPPORTED_OPERATION"
    assert disconnect_error.value.code == "UNSUPPORTED_OPERATION"


@pytest.mark.parametrize("alias", ["Dallas", "../dallas", "dallas.example", ""])
def test_target_alias_has_safe_provider_neutral_shape(alias: str) -> None:
    with pytest.raises(ValidationError):
        VpnTarget(alias=alias, label="Invalid", provider_target="opaque-provider-value")

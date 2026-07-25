"""Tests for the unregistered read-only Mullvad provider adapter."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from snarkyctl.providers.base import (
    GatewayMode,
    ProviderError,
    ProviderPreflightStatus,
    VpnState,
    VpnTarget,
)
from snarkyctl.providers.mullvad import (
    MAX_OUTPUT_LENGTH,
    CommandResult,
    MullvadAccountState,
    MullvadProvider,
    parse_account_state,
    parse_lockdown_mode,
    parse_status,
    parse_version,
    run_command,
)
from snarkyctl.providers.registry import available_providers


CONNECTED_STATUS = """{
  "state": "connected",
  "details": {
    "endpoint": {
      "endpoint": {"address": "198.51.100.1:51820", "protocol": "udp"},
      "tunnel_interface": "wg-mullvad"
    },
    "location": {
      "latitude": 57.7,
      "longitude": 11.9,
      "ipv4": "203.0.113.8",
      "ipv6": null,
      "mullvad_exit_ip": true,
      "hostname": "se-got-wg-001",
      "city": "Gothenburg",
      "country": "Sweden",
      "entry_hostname": null,
      "entry_city": null,
      "entry_country": null
    },
    "feature_indicators": []
  }
}"""


def test_mullvad_remains_unregistered_in_phase_two() -> None:
    assert available_providers() == ("nordvpn",)


def test_parse_connected_status_uses_only_sanitized_details() -> None:
    status = parse_status(CONNECTED_STATUS)

    assert status.state is VpnState.CONNECTED
    assert status.provider == "mullvad"
    assert status.gateway_mode is GatewayMode.VPN
    assert status.display_name == "se-got-wg-001"
    assert status.interface == "wg-mullvad"
    assert status.details == {
        "hostname": "se-got-wg-001",
        "country": "Sweden",
        "city": "Gothenburg",
    }
    assert "203.0.113.8" not in str(status.model_dump())


@pytest.mark.parametrize(
    ("locked_down", "mode"),
    [(True, GatewayMode.LOCKED), (False, GatewayMode.DIRECT)],
)
def test_parse_disconnected_status_reports_observed_lockdown(
    locked_down: bool, mode: GatewayMode
) -> None:
    status = parse_status(
        f'{{"state":"disconnected","details":{{"location":null,'
        f'"locked_down":{str(locked_down).lower()}}}}}'
    )

    assert status.state is VpnState.DISCONNECTED
    assert status.leak_protection_active is locked_down
    assert status.gateway_mode is mode


@pytest.mark.parametrize(
    ("raw_state", "state"),
    [
        ("connecting", VpnState.CONNECTING),
        ("disconnecting", VpnState.DISCONNECTING),
        ("error", VpnState.FAILED),
    ],
)
def test_parse_transitional_and_error_states(raw_state: str, state: VpnState) -> None:
    status = parse_status(f'{{"state":"{raw_state}","details":{{}}}}')

    assert status.state is state
    assert status.gateway_mode is GatewayMode.UNKNOWN
    assert status.diagnostic_code == (
        "MULLVAD_TUNNEL_ERROR" if state is VpnState.FAILED else None
    )


def test_status_accepts_documented_logged_out_warning_before_json() -> None:
    status = parse_status(
        "Warning: You are not logged in to an account.\n"
        '{"state":"disconnected","details":{"location":null,"locked_down":true}}\n'
    )

    assert status.state is VpnState.DISCONNECTED


@pytest.mark.parametrize(
    "output",
    [
        "",
        "Connected\n",
        '{"state":"future_state","details":{}}\n',
        '{"state":"disconnected","details":{"locked_down":"yes"}}\n',
        '{"state":"connected","details":{"endpoint":{"tunnel_interface":"../../bad"}}}\n',
        "unexpected\n{\"state\":\"disconnected\",\"details\":{}}\n",
    ],
)
def test_status_rejects_malformed_or_unsafe_output(output: str) -> None:
    with pytest.raises(ProviderError):
        parse_status(output)


@pytest.mark.parametrize(
    ("output", "enabled"),
    [
        ("Block traffic when the VPN is disconnected: on\n", True),
        ("Block traffic when the VPN is disconnected: off\n", False),
    ],
)
def test_parse_lockdown_mode(output: str, enabled: bool) -> None:
    assert parse_lockdown_mode(output) is enabled


def test_parse_lockdown_mode_rejects_unknown_output() -> None:
    with pytest.raises(ProviderError) as error:
        parse_lockdown_mode("Lockdown mode: enabled\n")
    assert error.value.code == "PROVIDER_OUTPUT_INVALID"


def test_parse_supported_version() -> None:
    version = parse_version(
        """Current version       : 2026.1
mullvad-daemon version: 2026.1
Is supported          : true
Suggested upgrade     : none
"""
    )

    assert version.cli_version == "2026.1"
    assert version.daemon_version == "2026.1"
    assert version.supported is True


@pytest.mark.parametrize(
    ("output", "state"),
    [
        ("Not logged in on any account\n", MullvadAccountState.LOGGED_OUT),
        ("This device has been revoked.\n", MullvadAccountState.REVOKED),
        (
            "Mullvad account:    1234123412341234\nDevice name: test\n",
            MullvadAccountState.LOGGED_IN,
        ),
        ("Unexpected output\n", MullvadAccountState.UNKNOWN),
    ],
)
def test_account_parser_retains_no_identifier(
    output: str, state: MullvadAccountState
) -> None:
    assert parse_account_state(output) is state


def test_read_only_adapter_uses_only_inspection_commands() -> None:
    calls: list[tuple[str, ...]] = []

    def runner(_executable: Path, arguments: object, _timeout: float) -> CommandResult:
        args = tuple(arguments)  # type: ignore[arg-type]
        calls.append(args)
        if args == ("status", "--json"):
            return CommandResult(0, CONNECTED_STATUS, "")
        if args == ("lockdown-mode", "get"):
            return CommandResult(
                0, "Block traffic when the VPN is disconnected: on\n", ""
            )
        raise AssertionError(f"unexpected command: {args}")

    provider = MullvadProvider(runner=runner)

    assert provider.status().state is VpnState.CONNECTED
    assert provider.settings().leak_protection_enabled is True
    assert calls == [("status", "--json"), ("lockdown-mode", "get")]


def test_all_mullvad_mutations_are_disabled() -> None:
    provider = MullvadProvider(
        runner=lambda *_args: (_ for _ in ()).throw(AssertionError("command executed"))
    )
    target = VpnTarget(alias="test", label="Test", provider_target="se")

    for operation in (
        lambda: provider.connect(target),
        provider.disconnect,
        lambda: provider.set_leak_protection(True),
    ):
        with pytest.raises(ProviderError) as error:
            operation()
        assert error.value.code == "UNSUPPORTED_OPERATION"


def test_preflight_uses_only_read_only_commands(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "mullvad"
    executable.write_text("", encoding="utf-8")
    executable.chmod(0o755)
    calls: list[tuple[str, ...]] = []

    def runner(_executable: Path, arguments: object, _timeout: float) -> CommandResult:
        args = tuple(arguments)  # type: ignore[arg-type]
        calls.append(args)
        outputs = {
            ("version",): (
                "Current version: 2026.1\nIs supported: true\nSuggested upgrade: none\n"
            ),
            ("status", "--json"): (
                '{"state":"disconnected","details":{"location":null,"locked_down":true}}\n'
            ),
            ("account", "get"): (
                "Mullvad account: 1234123412341234\nDevice name: test\n"
            ),
            ("lockdown-mode", "get"): (
                "Block traffic when the VPN is disconnected: on\n"
            ),
        }
        return CommandResult(0, outputs[args], "")

    checks = MullvadProvider(executable=executable, runner=runner).preflight()

    assert all(check.status is ProviderPreflightStatus.PASS for check in checks)
    assert calls == [
        ("version",),
        ("status", "--json"),
        ("account", "get"),
        ("lockdown-mode", "get"),
    ]
    assert "1234123412341234" not in str(checks)


def test_preflight_stops_after_version_failure(tmp_path: Path) -> None:
    executable = tmp_path / "mullvad"
    executable.write_text("", encoding="utf-8")
    executable.chmod(0o755)
    provider = MullvadProvider(
        executable=executable,
        runner=lambda *_args: CommandResult(1, "", "daemon unavailable"),
    )

    checks = provider.preflight()

    assert [check.status for check in checks] == [
        ProviderPreflightStatus.PASS,
        ProviderPreflightStatus.FAIL,
    ]
    assert "daemon unavailable" not in str(checks)


def test_command_runner_uses_argument_array(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[list[str]] = []

    def fake_run(arguments: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, stdout="{}", stderr="")

    monkeypatch.setattr("snarkyctl.providers.mullvad.subprocess.run", fake_run)
    run_command(Path("/usr/bin/mullvad"), ("status", "--json"), 5)

    assert captured == [["/usr/bin/mullvad", "status", "--json"]]


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (FileNotFoundError(), "PROVIDER_UNAVAILABLE"),
        (PermissionError(), "PROVIDER_PERMISSION_DENIED"),
        (subprocess.TimeoutExpired("mullvad", 5), "PROVIDER_TIMEOUT"),
    ],
)
def test_command_runner_maps_operating_system_failures(
    monkeypatch: pytest.MonkeyPatch, failure: BaseException, code: str
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise failure

    monkeypatch.setattr("snarkyctl.providers.mullvad.subprocess.run", fail)
    with pytest.raises(ProviderError) as error:
        run_command(Path("/usr/bin/mullvad"), ("status", "--json"), 5)
    assert error.value.code == code


def test_command_runner_rejects_large_output(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            [], 0, stdout="x" * (MAX_OUTPUT_LENGTH + 1), stderr=""
        )

    monkeypatch.setattr("snarkyctl.providers.mullvad.subprocess.run", fake_run)
    with pytest.raises(ProviderError) as error:
        run_command(Path("/usr/bin/mullvad"), ("status", "--json"), 5)
    assert error.value.code == "PROVIDER_OUTPUT_TOO_LARGE"

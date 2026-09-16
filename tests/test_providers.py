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
    MAX_ERROR_DETAIL_LENGTH,
    MAX_OUTPUT_LENGTH,
    CommandResult,
    NordVpnProvider,
    parse_settings,
    parse_status,
    run_command,
)
from snarkyctl.providers.placeholder import PlaceholderProvider
from snarkyctl.targets.models import (
    MAX_TARGET_OPTIONS,
    SelectorFieldType,
    SelectorOptionSource,
    StoredTarget,
)


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


def test_nordvpn_target_schema_declares_dynamic_discovery() -> None:
    provider = NordVpnProvider(runner=lambda *_args: CommandResult(0, "", ""))
    schema = provider.target_schema()
    kinds = {item.kind: item for item in schema.selector_kinds}

    country = kinds["country"].fields[0]
    city_country, city = kinds["city"].fields
    group = kinds["group"].fields[0]
    server = kinds["server"].fields[0]

    assert provider.capabilities.target_discovery
    assert kinds["country"].label == "Fastest in country"
    assert kinds["city"].label == "Fastest in city"
    assert country.field_type is SelectorFieldType.CHOICE
    assert country.option_source is SelectorOptionSource.PROVIDER
    assert city_country.option_source is SelectorOptionSource.PROVIDER
    assert city.option_source is SelectorOptionSource.PROVIDER
    assert city.depends_on == ("country",)
    assert group.option_source is SelectorOptionSource.PROVIDER
    assert server.field_type is SelectorFieldType.TEXT
    assert server.option_source is SelectorOptionSource.STATIC


@pytest.mark.parametrize("kind", ["country", "city"])
def test_nordvpn_discovers_countries_for_country_fields(kind: str) -> None:
    calls: list[tuple[str, ...]] = []

    def runner(_executable: object, arguments: object, _timeout: float) -> CommandResult:
        args = tuple(arguments)  # type: ignore[arg-type]
        calls.append(args)
        return CommandResult(0, "United States\nCanada\n", "")

    options = NordVpnProvider(runner=runner).target_options(kind, "country", {})

    assert calls == [("countries",)]
    assert [(item.value, item.label) for item in options.options] == [
        ("united_states", "United States"),
        ("canada", "Canada"),
    ]


def test_nordvpn_discovers_cities_with_country_context() -> None:
    calls: list[tuple[str, ...]] = []

    def runner(_executable: object, arguments: object, _timeout: float) -> CommandResult:
        args = tuple(arguments)  # type: ignore[arg-type]
        calls.append(args)
        return CommandResult(0, "New_York\nLos_Angeles\n", "")

    options = NordVpnProvider(runner=runner).target_options(
        "city",
        "city",
        {"country": "US"},
    )

    assert calls == [("cities", "us")]
    assert [(item.value, item.label) for item in options.options] == [
        ("new_york", "New York"),
        ("los_angeles", "Los Angeles"),
    ]


def test_nordvpn_discovers_server_groups() -> None:
    calls: list[tuple[str, ...]] = []

    def runner(_executable: object, arguments: object, _timeout: float) -> CommandResult:
        args = tuple(arguments)  # type: ignore[arg-type]
        calls.append(args)
        return CommandResult(0, "P2P\nDouble_VPN\nOnion_Over_VPN\n", "")

    options = NordVpnProvider(runner=runner).target_options("group", "group", {})

    assert calls == [("groups",)]
    assert [(item.value, item.label) for item in options.options] == [
        ("p2p", "P2P"),
        ("double_vpn", "Double VPN"),
        ("onion_over_vpn", "Onion Over VPN"),
    ]


@pytest.mark.parametrize(
    "context",
    [
        {},
        {"country": None},
        {"country": "--help"},
        {"country": "us", "extra": "bad"},
    ],
)
def test_nordvpn_city_discovery_rejects_invalid_context(
    context: dict[str, str | int | bool | None],
) -> None:
    def forbidden(*_args: object) -> CommandResult:
        raise AssertionError("invalid discovery context must not invoke NordVPN")

    provider = NordVpnProvider(runner=forbidden)
    with pytest.raises(ProviderError) as error:
        provider.target_options("city", "city", context)
    assert error.value.code == "INVALID_TARGET_CONTEXT"


def test_nordvpn_discovery_rejects_unsupported_selector_field() -> None:
    provider = NordVpnProvider(runner=lambda *_args: CommandResult(0, "", ""))
    with pytest.raises(ProviderError) as error:
        provider.target_options("server", "server", {})
    assert error.value.code == "UNSUPPORTED_TARGET_DISCOVERY"


@pytest.mark.parametrize(
    "output",
    [
        "",
        "New York\nNew_York\n",
        "\x1b[31mParis\n",
        "x" * 101 + "\n",
    ],
)
def test_nordvpn_discovery_rejects_malformed_output(output: str) -> None:
    provider = NordVpnProvider(
        runner=lambda *_args: CommandResult(0, output, "")
    )
    with pytest.raises(ProviderError) as error:
        provider.target_options("city", "city", {"country": "us"})
    assert error.value.code == "PROVIDER_OUTPUT_INVALID"


def test_nordvpn_discovery_rejects_excessive_option_count() -> None:
    output = "\n".join(
        f"Country_{index}" for index in range(MAX_TARGET_OPTIONS + 1)
    )
    provider = NordVpnProvider(
        runner=lambda *_args: CommandResult(0, output, "")
    )
    with pytest.raises(ProviderError) as error:
        provider.target_options("country", "country", {})
    assert error.value.code == "PROVIDER_OUTPUT_TOO_LARGE"


@pytest.mark.parametrize(
    ("selector", "expected"),
    [
        ({"kind": "recommended"}, ("connect",)),
        ({"kind": "country", "country": "US"}, ("connect", "us")),
        (
            {"kind": "city", "country": "US", "city": "Dallas"},
            ("connect", "us", "Dallas"),
        ),
        ({"kind": "group", "group": "P2P"}, ("connect", "P2P")),
        ({"kind": "server", "server": "us4955"}, ("connect", "us4955")),
        ({"kind": "legacy", "value": "United States"}, ("connect", "United States")),
    ],
)
def test_nordvpn_structured_selectors_use_fixed_arguments(
    selector: dict[str, str], expected: tuple[str, ...]
) -> None:
    calls: list[tuple[str, ...]] = []

    def runner(_executable: object, arguments: object, _timeout: float) -> CommandResult:
        args = tuple(arguments)  # type: ignore[arg-type]
        calls.append(args)
        return CommandResult(0, CONNECTED_STATUS if args == ("status",) else "", "")

    stored = StoredTarget(alias="test", label="Test", position=0, selector=selector)
    NordVpnProvider(runner=runner).connect_stored(stored)
    assert calls == [expected, ("status",)]


@pytest.mark.parametrize(
    "selector",
    [
        {"kind": "unknown"},
        {"kind": "recommended", "extra": "bad"},
        {"kind": "country"},
        {"kind": "server", "server": "--help"},
    ],
)
def test_nordvpn_rejects_malformed_structured_selectors(
    selector: dict[str, str],
) -> None:
    provider = NordVpnProvider(runner=lambda *_args: CommandResult(0, "", ""))
    with pytest.raises(ProviderError) as error:
        provider.validate_selector(selector)
    assert error.value.code == "INVALID_TARGET"


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


@pytest.mark.parametrize(("enabled", "value"), [(True, "on"), (False, "off")])
def test_nordvpn_configures_kill_switch(enabled: bool, value: str) -> None:
    calls: list[tuple[str, ...]] = []

    def runner(_executable: object, arguments: object, _timeout: float) -> CommandResult:
        args = tuple(arguments)  # type: ignore[arg-type]
        calls.append(args)
        output = (
            f"Kill Switch: {'enabled' if enabled else 'disabled'}\n"
            "Firewall: enabled\n"
            if args == ("settings",)
            else "Setting updated\n"
        )
        return CommandResult(0, output, "")

    settings = NordVpnProvider(runner=runner).set_leak_protection(enabled)

    assert calls == [("set", "killswitch", value), ("settings",)]
    assert settings.leak_protection_enabled is enabled


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
    assert str(error.value) == "NordVPN command failed with exit status 7: failure"


def test_nordvpn_command_failure_uses_stdout_when_stderr_is_empty() -> None:
    provider = NordVpnProvider(
        runner=lambda *_args: CommandResult(1, "Permission denied\nTry again.\n", "")
    )
    with pytest.raises(ProviderError) as error:
        provider.status()
    assert str(error.value) == (
        "NordVPN command failed with exit status 1: Permission denied Try again."
    )


def test_nordvpn_command_failure_without_output_keeps_generic_message() -> None:
    provider = NordVpnProvider(runner=lambda *_args: CommandResult(1, "", ""))
    with pytest.raises(ProviderError) as error:
        provider.status()
    assert str(error.value) == "NordVPN command failed with exit status 1"


def test_nordvpn_command_failure_sanitizes_and_bounds_detail() -> None:
    provider = NordVpnProvider(
        runner=lambda *_args: CommandResult(
            1,
            "",
            "denied\x00\n" + "x" * MAX_ERROR_DETAIL_LENGTH,
        )
    )
    with pytest.raises(ProviderError) as error:
        provider.status()
    detail = str(error.value).partition(": ")[2]
    assert "\x00" not in detail
    assert "\n" not in detail
    assert len(detail) == MAX_ERROR_DETAIL_LENGTH
    assert detail.endswith("...")


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

"""Tests for the provider-neutral upstream VPN boundary."""

import pytest
from pydantic import ValidationError

from snarkyctl.providers import (
    ProviderError,
    VpnState,
    VpnTarget,
    available_providers,
    create_provider,
)
from snarkyctl.providers.nordvpn import NordVpnProvider
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


@pytest.mark.parametrize("operation", ["status", "connect", "disconnect"])
def test_nordvpn_skeleton_executes_no_operation(operation: str) -> None:
    provider = NordVpnProvider()

    with pytest.raises(ProviderError) as error:
        if operation == "status":
            provider.status()
        elif operation == "connect":
            provider.connect(target())
        else:
            provider.disconnect()

    assert error.value.code == "NOT_IMPLEMENTED"


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

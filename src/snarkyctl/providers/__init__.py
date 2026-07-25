"""Provider-neutral upstream VPN interfaces and built-in adapters."""

from snarkyctl.providers.base import (
    GatewayMode,
    ProviderCapabilities,
    ProviderError,
    ProviderPreflightCheck,
    ProviderPreflightStatus,
    ProviderRuntimeConfig,
    VpnProvider,
    VpnSettings,
    VpnState,
    VpnStatus,
    VpnTarget,
)
from snarkyctl.providers.registry import available_providers, create_provider

__all__ = [
    "ProviderCapabilities",
    "ProviderError",
    "ProviderPreflightCheck",
    "ProviderPreflightStatus",
    "ProviderRuntimeConfig",
    "GatewayMode",
    "VpnProvider",
    "VpnState",
    "VpnStatus",
    "VpnSettings",
    "VpnTarget",
    "available_providers",
    "create_provider",
]

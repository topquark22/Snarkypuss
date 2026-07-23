"""Provider-neutral upstream VPN interfaces and built-in adapters."""

from snarkyctl.providers.base import (
    ProviderCapabilities,
    ProviderError,
    VpnProvider,
    VpnState,
    VpnStatus,
    VpnTarget,
)
from snarkyctl.providers.registry import available_providers, create_provider

__all__ = [
    "ProviderCapabilities",
    "ProviderError",
    "VpnProvider",
    "VpnState",
    "VpnStatus",
    "VpnTarget",
    "available_providers",
    "create_provider",
]

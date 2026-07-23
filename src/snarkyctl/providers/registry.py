"""Fixed registry of trusted upstream VPN adapters."""

from collections.abc import Callable
from types import MappingProxyType

from snarkyctl.providers.base import ProviderError, VpnProvider
from snarkyctl.providers.nordvpn import NordVpnProvider

type ProviderFactory = Callable[[], VpnProvider]

_PROVIDER_FACTORIES: MappingProxyType[str, ProviderFactory] = MappingProxyType(
    {
        "nordvpn": NordVpnProvider,
    }
)


def available_providers() -> tuple[str, ...]:
    """Return trusted provider names compiled into this release."""
    return tuple(sorted(_PROVIDER_FACTORIES))


def create_provider(name: str) -> VpnProvider:
    """Create one trusted provider or reject an unknown configuration value."""
    try:
        factory = _PROVIDER_FACTORIES[name]
    except KeyError as exc:
        raise ProviderError("UNKNOWN_PROVIDER", f"Unknown VPN provider: {name}") from exc
    return factory()

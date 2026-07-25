"""Fixed registry of trusted upstream VPN adapters."""

from collections.abc import Callable
from types import MappingProxyType

from snarkyctl.providers.base import ProviderError, ProviderRuntimeConfig, VpnProvider
from snarkyctl.providers.nordvpn import NordVpnProvider

type ProviderFactory = Callable[[float, ProviderRuntimeConfig | None], VpnProvider]

_PROVIDER_FACTORIES: MappingProxyType[str, ProviderFactory] = MappingProxyType(
    {
        "nordvpn": lambda timeout, config: NordVpnProvider(
            executable=config.executable if config is not None else None,
            timeout_seconds=timeout,
        ),
    }
)


def available_providers() -> tuple[str, ...]:
    """Return trusted provider names compiled into this release."""
    return tuple(sorted(_PROVIDER_FACTORIES))


def create_provider(
    name: str,
    *,
    timeout_seconds: float = 45.0,
    provider_config: ProviderRuntimeConfig | None = None,
) -> VpnProvider:
    """Create one trusted provider or reject an unknown configuration value."""
    try:
        factory = _PROVIDER_FACTORIES[name]
    except KeyError as exc:
        raise ProviderError("UNKNOWN_PROVIDER", f"Unknown VPN provider: {name}") from exc
    if provider_config is not None and provider_config.provider != name:
        raise ProviderError(
            "INVALID_PROVIDER_CONFIGURATION",
            f"Configuration for {provider_config.provider} cannot be used with {name}.",
        )
    return factory(timeout_seconds, provider_config)

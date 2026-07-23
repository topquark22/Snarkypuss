"""Non-registered, non-mutating provider used by tests and local development."""

from snarkyctl.providers.base import (
    ProviderCapabilities,
    ProviderError,
    VpnProvider,
    VpnSettings,
    VpnState,
    VpnStatus,
    VpnTarget,
)


class PlaceholderProvider(VpnProvider):
    """Safe adapter that reports disconnected and rejects every mutation."""

    name = "placeholder"
    capabilities = ProviderCapabilities(
        connect=False,
        disconnect=False,
        target_selection=False,
        server_details=False,
    )

    def status(self) -> VpnStatus:
        return VpnStatus(state=VpnState.DISCONNECTED, provider=self.name)

    def settings(self) -> VpnSettings:
        return VpnSettings(provider=self.name, leak_protection_enabled=None)

    def connect(self, target: VpnTarget) -> VpnStatus:
        del target
        raise ProviderError("UNSUPPORTED_OPERATION", "Placeholder provider cannot connect.")

    def disconnect(self) -> VpnStatus:
        raise ProviderError("UNSUPPORTED_OPERATION", "Placeholder provider cannot disconnect.")

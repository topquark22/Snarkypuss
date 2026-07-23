"""NordVPN upstream adapter skeleton.

No external command is executed yet. Real CLI integration and parsing will be
added only after fixtures from the deployed gateway are captured and tested.
"""

from snarkyctl.providers.base import (
    ProviderCapabilities,
    ProviderError,
    VpnProvider,
    VpnStatus,
    VpnTarget,
)


class NordVpnProvider(VpnProvider):
    """Built-in adapter for the NordVPN Linux CLI."""

    name = "nordvpn"
    capabilities = ProviderCapabilities(
        connect=True,
        disconnect=True,
        target_selection=True,
        server_details=True,
    )

    def status(self) -> VpnStatus:
        raise ProviderError("NOT_IMPLEMENTED", "NordVPN status is not implemented yet.")

    def connect(self, target: VpnTarget) -> VpnStatus:
        del target
        raise ProviderError("NOT_IMPLEMENTED", "NordVPN connection is not implemented yet.")

    def disconnect(self) -> VpnStatus:
        raise ProviderError("NOT_IMPLEMENTED", "NordVPN disconnection is not implemented yet.")

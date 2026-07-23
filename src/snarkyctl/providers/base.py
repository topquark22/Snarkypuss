"""Provider-neutral models for an optional upstream VPN."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from enum import StrEnum
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field


class VpnState(StrEnum):
    """Common lifecycle states reported by every upstream VPN adapter."""

    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    DISCONNECTING = "DISCONNECTING"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class ProviderCapabilities(BaseModel):
    """Operations and information supported by a provider adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    connect: bool
    disconnect: bool
    target_selection: bool
    server_details: bool


class VpnTarget(BaseModel):
    """Root-configured target passed to a provider adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    alias: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    label: str = Field(min_length=1, max_length=100)
    provider_target: str = Field(min_length=1, max_length=200)


class VpnStatus(BaseModel):
    """Provider-neutral upstream VPN status."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: VpnState
    provider: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    target: str | None = None
    display_name: str | None = None
    interface: str | None = None
    connected_since: datetime | None = None
    diagnostic_code: str | None = None
    details: dict[str, str] = Field(default_factory=dict)


class ProviderError(RuntimeError):
    """Controlled failure raised by a provider adapter."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class VpnProvider(ABC):
    """Trusted root-side adapter for one upstream VPN implementation."""

    name: ClassVar[str]
    capabilities: ClassVar[ProviderCapabilities]

    @abstractmethod
    def status(self) -> VpnStatus:
        """Return the current provider-neutral VPN status."""

    @abstractmethod
    def connect(self, target: VpnTarget) -> VpnStatus:
        """Connect to one root-configured target and return resulting status."""

    @abstractmethod
    def disconnect(self) -> VpnStatus:
        """Disconnect the upstream VPN and return resulting status."""

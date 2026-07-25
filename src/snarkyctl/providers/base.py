"""Provider-neutral models for an optional upstream VPN."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from snarkyctl.targets.models import JsonObject, ProviderTargetSchema, StoredTarget


class VpnState(StrEnum):
    """Common lifecycle states reported by every upstream VPN adapter."""

    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    DISCONNECTING = "DISCONNECTING"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class GatewayMode(StrEnum):
    """Observed relationship between client traffic and the public Internet."""

    VPN = "VPN"
    LOCKED = "LOCKED"
    DIRECT = "DIRECT"
    UNKNOWN = "UNKNOWN"


class ProviderCapabilities(BaseModel):
    """Operations and information supported by a provider adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    connect: bool
    disconnect: bool
    target_selection: bool
    server_details: bool
    leak_protection_status: bool = Field(default=False, exclude=True)
    leak_protection_configuration: bool = False
    locked_mode: bool = Field(default=False, exclude=True)
    direct_mode: bool = Field(default=False, exclude=True)


class ProviderPreflightStatus(StrEnum):
    """Provider-owned read-only preflight result severity."""

    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    SKIP = "SKIP"


class ProviderPreflightCheck(BaseModel):
    """One bounded provider check returned to the core preflight runner."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    check_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    status: ProviderPreflightStatus
    message: str = Field(min_length=1, max_length=500)


class ProviderRuntimeConfig(BaseModel):
    """Common, bounded runtime configuration passed to a trusted adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    executable: Path
    service: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.@-]{0,127}\.service$")
    expected_interfaces: tuple[str, ...] = Field(default=(), max_length=8)

    @field_validator("executable")
    @classmethod
    def require_safe_executable(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("provider executable path must be absolute")
        if any(part in {"", ".", ".."} for part in value.parts):
            raise ValueError("provider executable path must be normalized")
        return value


class VpnTarget(BaseModel):
    """Root-configured target passed to a provider adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    alias: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    label: str = Field(min_length=1, max_length=100)
    provider_target: str = Field(min_length=1, max_length=200)


class VpnTargetSummary(BaseModel):
    """Provider-neutral target information safe to expose to clients."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    alias: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    label: str = Field(min_length=1, max_length=100)


class VpnTargetCatalog(BaseModel):
    """Sanitized target catalogue and capabilities for the active provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[2] = 2
    provider: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    capabilities: ProviderCapabilities
    targets: tuple[VpnTargetSummary, ...]


class VpnStatus(BaseModel):
    """Provider-neutral upstream VPN status."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: VpnState
    provider: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    gateway_mode: GatewayMode = GatewayMode.UNKNOWN
    leak_protection_active: bool | None = None
    target: str | None = None
    display_name: str | None = None
    interface: str | None = None
    connected_since: datetime | None = None
    diagnostic_code: str | None = None
    details: dict[str, str] = Field(default_factory=dict)


class VpnSettings(BaseModel):
    """Provider-neutral settings relevant to safe control decisions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    leak_protection_enabled: bool | None
    technology: str | None = None
    routing_enabled: bool | None = None
    firewall_enabled: bool | None = None
    firewall_mark: str | None = None


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
    def settings(self) -> VpnSettings:
        """Return provider settings needed for safe control decisions."""

    @abstractmethod
    def connect(self, target: VpnTarget) -> VpnStatus:
        """Connect to one root-configured target and return resulting status."""

    def target_schema(self) -> ProviderTargetSchema:
        """Return the provider's reviewed target selector schema."""
        raise ProviderError(
            "UNSUPPORTED_TARGET_SELECTION",
            f"{self.name} does not support target selection.",
        )

    def validate_selector(self, selector: JsonObject) -> JsonObject:
        """Validate and normalize one provider-owned selector document."""
        if selector.get("kind") != "legacy" or set(selector) != {"kind", "value"}:
            raise ProviderError("INVALID_TARGET", "Only a legacy selector is supported.")
        value = selector.get("value")
        if not isinstance(value, str) or not value or len(value) > 200:
            raise ProviderError("INVALID_TARGET", "Legacy target value is invalid.")
        return {"kind": "legacy", "value": value}

    def import_legacy_target(self, value: str) -> JsonObject:
        """Convert an existing YAML provider target without guessing its meaning."""
        return self.validate_selector({"kind": "legacy", "value": value})

    def connect_stored(self, target: StoredTarget) -> VpnStatus:
        """Connect using a validated structured target."""
        selector = self.validate_selector(target.selector)
        value = selector.get("value")
        if selector.get("kind") != "legacy" or not isinstance(value, str):
            raise ProviderError("INVALID_TARGET", "Provider cannot connect with this selector.")
        return self.connect(
            VpnTarget(alias=target.alias, label=target.label, provider_target=value)
        )

    @abstractmethod
    def disconnect(self) -> VpnStatus:
        """Disconnect the upstream VPN and return resulting status."""

    def set_leak_protection(self, enabled: bool) -> VpnSettings:
        """Enable or disable provider leak protection when supported."""
        del enabled
        raise ProviderError(
            "UNSUPPORTED_OPERATION",
            f"{self.name} cannot configure leak protection.",
        )

    def preflight(self) -> tuple[ProviderPreflightCheck, ...]:
        """Return provider-owned read-only checks without changing provider state."""
        return ()

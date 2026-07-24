"""Typed, provider-neutral SnarkyCtl configuration loading."""

from __future__ import annotations

import os
import stat
from ipaddress import IPv4Address, IPv4Interface, IPv4Network
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from snarkyctl.providers.base import VpnTarget
from snarkyctl.providers.registry import available_providers

DEFAULT_CONFIG_PATH = Path("/etc/snarkyctl/snarkyctl.yaml")
MAX_CONFIG_SIZE = 64 * 1024
INTERFACE_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,14}$"


class ConfigError(RuntimeError):
    """A configuration file could not be read or validated safely."""


class NetworkConfig(BaseModel):
    """Interfaces and address ranges that define the gateway boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    management_interface: str = Field(pattern=INTERFACE_PATTERN)
    management_address: IPv4Interface
    client_subnet: IPv4Network
    public_interface: str = Field(pattern=INTERFACE_PATTERN)

    @model_validator(mode="after")
    def validate_network(self) -> NetworkConfig:
        if self.management_interface == self.public_interface:
            raise ValueError("management_interface and public_interface must differ")
        if self.management_address.ip not in self.client_subnet:
            raise ValueError("management_address must belong to client_subnet")
        return self


class WebConfig(BaseModel):
    """Private HTTPS listener and credential paths."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    bind_address: IPv4Address
    port: int = Field(ge=1, le=65535)
    auth_file: Path
    tls_certificate: Path
    tls_private_key: Path
    request_timeout_seconds: float = Field(gt=0, le=60)

    @field_validator("auth_file", "tls_certificate", "tls_private_key")
    @classmethod
    def require_absolute_path(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("path must be absolute")
        return value


class ControlConfig(BaseModel):
    """Local privileged-daemon connection and operation limits."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    socket_path: Path
    operation_timeout_seconds: float = Field(gt=0, le=300)

    @field_validator("socket_path")
    @classmethod
    def require_absolute_path(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("path must be absolute")
        return value


class StatusConfig(BaseModel):
    """Read-only external status sources and their limits."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    public_ip_url: str = "https://api.ipify.org"
    public_ip_timeout_seconds: float = Field(default=5, gt=0, le=15)

    @field_validator("public_ip_url")
    @classmethod
    def require_safe_https_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        try:
            parsed.port
        except ValueError as exc:
            raise ValueError("public_ip_url contains an invalid port") from exc
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise ValueError("public_ip_url must be an HTTPS URL without credentials or a fragment")
        return value


class UpstreamVpnConfig(BaseModel):
    """Trusted adapter selection and its root-owned target document."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    expected_interfaces: tuple[str, ...] = Field(min_length=1, max_length=8)
    targets_file: Path

    @field_validator("provider")
    @classmethod
    def require_compiled_provider(cls, value: str) -> str:
        if value not in available_providers():
            choices = ", ".join(available_providers())
            raise ValueError(
                f"provider is not compiled into this release; choose one of: {choices}"
            )
        return value

    @field_validator("expected_interfaces")
    @classmethod
    def validate_interfaces(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("expected_interfaces must not contain duplicates")
        import re

        if any(re.fullmatch(INTERFACE_PATTERN, item) is None for item in value):
            raise ValueError("expected_interfaces contains an invalid Linux interface name")
        return value

    @field_validator("targets_file")
    @classmethod
    def require_absolute_path(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("path must be absolute")
        return value


class SnarkyCtlConfig(BaseModel):
    """Versioned main configuration document."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    network: NetworkConfig
    web: WebConfig
    control: ControlConfig
    status: StatusConfig = StatusConfig()
    upstream_vpn: UpstreamVpnConfig

    @model_validator(mode="after")
    def validate_boundaries(self) -> SnarkyCtlConfig:
        if self.web.bind_address != self.network.management_address.ip:
            raise ValueError("web.bind_address must equal network.management_address")
        reserved = {self.network.management_interface, self.network.public_interface}
        overlap = reserved.intersection(self.upstream_vpn.expected_interfaces)
        if overlap:
            raise ValueError(
                "upstream VPN interfaces must differ from management and public interfaces"
            )
        return self


class TargetConfig(BaseModel):
    """Versioned authoritative target allowlist."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    targets: tuple[VpnTarget, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def require_unique_aliases(self) -> TargetConfig:
        aliases = [target.alias for target in self.targets]
        if len(set(aliases)) != len(aliases):
            raise ValueError("target aliases must be unique")
        return self


class LoadedConfig(BaseModel):
    """Validated main configuration and target allowlist."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    settings: SnarkyCtlConfig
    targets: TargetConfig


def _read_yaml(path: Path) -> Any:
    """Read one bounded regular YAML file without following a final symlink."""
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ConfigError(f"cannot open {path}: {exc.strerror}") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ConfigError(f"{path} is not a regular file")
        if metadata.st_size > MAX_CONFIG_SIZE:
            raise ConfigError(f"{path} exceeds the {MAX_CONFIG_SIZE}-byte limit")
        with os.fdopen(descriptor, encoding="utf-8") as stream:
            descriptor = -1
            try:
                data = yaml.safe_load(stream)
            except (UnicodeError, yaml.YAMLError) as exc:
                raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a YAML mapping at its top level")
    return data


def _validate[ConfigModel: BaseModel](
    model: type[ConfigModel], data: Any, path: Path
) -> ConfigModel:
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"invalid configuration in {path}:\n{exc}") from exc


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> LoadedConfig:
    """Load and validate the main document and its authoritative targets."""
    settings = _validate(SnarkyCtlConfig, _read_yaml(path), path)
    targets_path = settings.upstream_vpn.targets_file
    targets = _validate(TargetConfig, _read_yaml(targets_path), targets_path)
    return LoadedConfig(settings=settings, targets=targets)

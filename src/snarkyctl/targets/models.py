"""Storage-independent models for provider target catalogues."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, RootModel, model_validator

MAX_TARGETS = 100
MAX_SELECTOR_FIELDS = 16
JsonScalar = str | int | bool | None
JsonObject = dict[str, JsonScalar]


class CatalogueRevision(RootModel[int]):
    """Optimistic-concurrency revision for one provider catalogue."""

    root: Annotated[int, Field(ge=0)]


class SelectorFieldType(StrEnum):
    """Reviewed field types supported by future generic clients."""

    TEXT = "text"
    CHOICE = "choice"
    BOOLEAN = "boolean"
    INTEGER = "integer"


class SelectorField(BaseModel):
    """One provider-declared selector field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")
    label: str = Field(min_length=1, max_length=100)
    field_type: SelectorFieldType
    required: bool = True
    choices: tuple[str, ...] = Field(default=(), max_length=100)
    max_length: int | None = Field(default=None, ge=1, le=200)


class SelectorKind(BaseModel):
    """One structured selector shape supported by a provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    label: str = Field(min_length=1, max_length=100)
    fields: tuple[SelectorField, ...] = Field(default=(), max_length=MAX_SELECTOR_FIELDS)


class ProviderTargetSchema(BaseModel):
    """Provider-declared, data-only selector schema."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    selector_kinds: tuple[SelectorKind, ...] = Field(max_length=16)
    max_targets: int = Field(default=MAX_TARGETS, ge=1, le=MAX_TARGETS)

    @model_validator(mode="after")
    def unique_kinds(self) -> ProviderTargetSchema:
        kinds = [item.kind for item in self.selector_kinds]
        if len(kinds) != len(set(kinds)):
            raise ValueError("selector kinds must be unique")
        return self


class StoredTarget(BaseModel):
    """One ordered target containing a provider-owned selector document."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    alias: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    label: str = Field(min_length=1, max_length=100)
    position: int = Field(ge=0, lt=MAX_TARGETS)
    selector: JsonObject

    @model_validator(mode="after")
    def bounded_selector(self) -> StoredTarget:
        if not self.selector or len(self.selector) > MAX_SELECTOR_FIELDS:
            raise ValueError("selector must contain between 1 and 16 fields")
        if any(len(key) > 32 for key in self.selector):
            raise ValueError("selector field names must be at most 32 characters")
        if any(isinstance(value, str) and len(value) > 200 for value in self.selector.values()):
            raise ValueError("selector string values must be at most 200 characters")
        return self


class TargetCatalogue(BaseModel):
    """Complete target catalogue for exactly one provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    revision: int = Field(ge=0)
    targets: tuple[StoredTarget, ...] = Field(default=(), max_length=MAX_TARGETS)

    @model_validator(mode="after")
    def validate_order(self) -> TargetCatalogue:
        aliases = [target.alias for target in self.targets]
        positions = [target.position for target in self.targets]
        if len(aliases) != len(set(aliases)):
            raise ValueError("target aliases must be unique")
        if positions != list(range(len(positions))):
            raise ValueError("target positions must be ordered and contiguous from zero")
        return self


class TargetCatalogueSummary(BaseModel):
    """Selector-free catalogue safe to expose to ordinary clients."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    revision: int = Field(ge=0)
    targets: tuple[tuple[str, str], ...]

    @classmethod
    def from_catalogue(cls, catalogue: TargetCatalogue) -> TargetCatalogueSummary:
        return cls(
            provider=catalogue.provider,
            revision=catalogue.revision,
            targets=tuple((target.alias, target.label) for target in catalogue.targets),
        )

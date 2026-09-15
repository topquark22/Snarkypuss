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


class SelectorOptionSource(StrEnum):
    """Source of values for one choice selector field."""

    STATIC = "static"
    PROVIDER = "provider"


class SelectorField(BaseModel):
    """One provider-declared selector field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")
    label: str = Field(min_length=1, max_length=100)
    field_type: SelectorFieldType
    required: bool = True
    choices: tuple[str, ...] = Field(default=(), max_length=100)
    option_source: SelectorOptionSource = SelectorOptionSource.STATIC
    depends_on: tuple[str, ...] = Field(default=(), max_length=MAX_SELECTOR_FIELDS)
    max_length: int | None = Field(default=None, ge=1, le=200)

    @model_validator(mode="after")
    def validate_option_source(self) -> SelectorField:
        if (
            self.option_source is SelectorOptionSource.PROVIDER
            and self.field_type is not SelectorFieldType.CHOICE
        ):
            raise ValueError("provider-backed options require a choice field")
        if self.option_source is SelectorOptionSource.PROVIDER and self.choices:
            raise ValueError("provider-backed choice fields cannot declare static choices")
        return self


class SelectorKind(BaseModel):
    """One structured selector shape supported by a provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    label: str = Field(min_length=1, max_length=100)
    fields: tuple[SelectorField, ...] = Field(default=(), max_length=MAX_SELECTOR_FIELDS)

    @model_validator(mode="after")
    def validate_dependencies(self) -> SelectorKind:
        field_names = [field.name for field in self.fields]
        if len(field_names) != len(set(field_names)):
            raise ValueError("selector field names must be unique")

        known_fields = set(field_names)
        dependencies = {field.name: field.depends_on for field in self.fields}
        for field in self.fields:
            if len(field.depends_on) != len(set(field.depends_on)):
                raise ValueError("selector field dependencies must be unique")
            if any(dependency not in known_fields for dependency in field.depends_on):
                raise ValueError(
                    "selector field dependencies must refer to fields in the same kind"
                )

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(field_name: str) -> None:
            if field_name in visiting:
                raise ValueError("selector field dependencies must not contain cycles")
            if field_name in visited:
                return
            visiting.add(field_name)
            for dependency in dependencies[field_name]:
                visit(dependency)
            visiting.remove(field_name)
            visited.add(field_name)

        for field_name in field_names:
            visit(field_name)
        return self


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


class TargetOption(BaseModel):
    """One provider-discovered selector value and its display label."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    value: str = Field(min_length=1, max_length=200)
    label: str = Field(min_length=1, max_length=100)


class TargetOptions(BaseModel):
    """Provider-neutral response for one dynamic selector field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    kind: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    field: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")
    options: tuple[TargetOption, ...] = Field(default=(), max_length=100)


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

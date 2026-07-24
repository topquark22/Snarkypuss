"""Tests for provider-neutral target models and repositories."""

import pytest
from pydantic import ValidationError

from snarkyctl.providers.base import VpnTarget
from snarkyctl.targets.models import (
    CatalogueRevision,
    StoredTarget,
    TargetCatalogue,
    TargetCatalogueSummary,
)
from snarkyctl.targets.repository import (
    MemoryTargetRepository,
    RepositoryError,
    YamlTargetRepository,
)


def stored(alias: str, position: int) -> StoredTarget:
    return StoredTarget(
        alias=alias,
        label=alias.title(),
        position=position,
        selector={"kind": "legacy", "value": alias},
    )


def test_catalogue_revision_cannot_be_negative() -> None:
    with pytest.raises(ValidationError):
        CatalogueRevision(-1)


def test_catalogue_requires_unique_ordered_targets() -> None:
    with pytest.raises(ValidationError, match="aliases must be unique"):
        TargetCatalogue(provider="test", revision=0, targets=(stored("one", 0), stored("one", 1)))
    with pytest.raises(ValidationError, match="ordered and contiguous"):
        TargetCatalogue(provider="test", revision=0, targets=(stored("one", 1),))


def test_selector_is_bounded_and_rejects_unknown_target_fields() -> None:
    with pytest.raises(ValidationError):
        StoredTarget(
            alias="one",
            label="One",
            position=0,
            selector={"kind": "legacy", "value": "x" * 201},
        )
    with pytest.raises(ValidationError):
        StoredTarget(
            alias="one",
            label="One",
            position=0,
            selector={"kind": "legacy"},
            unexpected=True,
        )


def test_catalogue_summary_omits_selectors() -> None:
    summary = TargetCatalogueSummary.from_catalogue(
        TargetCatalogue(provider="test", revision=4, targets=(stored("one", 0),))
    )
    assert summary.model_dump() == {
        "provider": "test",
        "revision": 4,
        "targets": (("one", "One"),),
    }


def test_memory_repository_replaces_atomically_and_checks_revision() -> None:
    repository = MemoryTargetRepository()
    replaced = repository.replace_catalogue("test", 0, (stored("one", 0),))
    assert replaced.revision == 1
    assert repository.get_catalogue("test") == replaced
    with pytest.raises(RepositoryError) as error:
        repository.replace_catalogue("test", 0, ())
    assert error.value.code == "CATALOG_CONFLICT"
    assert repository.get_catalogue("test") == replaced


def test_yaml_repository_imports_legacy_values_and_is_read_only() -> None:
    repository = YamlTargetRepository(
        "test",
        (VpnTarget(alias="one", label="One", provider_target="provider-one"),),
        lambda value: {"kind": "legacy", "value": value},
    )
    catalogue = repository.get_catalogue("test")
    assert catalogue.targets[0].selector["value"] == "provider-one"
    with pytest.raises(RepositoryError) as error:
        repository.replace_catalogue("test", 0, ())
    assert error.value.code == "READ_ONLY_REPOSITORY"

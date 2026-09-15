"""Tests for provider-neutral target discovery models."""

import pytest
from pydantic import ValidationError

from snarkyctl.providers import ProviderError
from snarkyctl.providers.placeholder import PlaceholderProvider
from snarkyctl.targets.models import (
    ProviderTargetSchema,
    SelectorField,
    SelectorFieldType,
    SelectorKind,
    SelectorOptionSource,
    TargetOption,
    TargetOptions,
)


def test_existing_static_selector_field_defaults_are_unchanged() -> None:
    field = SelectorField(
        name="country",
        label="Country",
        field_type=SelectorFieldType.TEXT,
        max_length=100,
    )

    assert field.option_source is SelectorOptionSource.STATIC
    assert field.depends_on == ()


def test_provider_backed_choice_field_can_declare_dependencies() -> None:
    schema = ProviderTargetSchema(
        provider="example",
        selector_kinds=(
            SelectorKind(
                kind="city",
                label="City",
                fields=(
                    SelectorField(
                        name="country",
                        label="Country",
                        field_type=SelectorFieldType.CHOICE,
                        option_source=SelectorOptionSource.PROVIDER,
                    ),
                    SelectorField(
                        name="city",
                        label="City",
                        field_type=SelectorFieldType.CHOICE,
                        option_source=SelectorOptionSource.PROVIDER,
                        depends_on=("country",),
                    ),
                ),
            ),
        ),
    )

    assert schema.selector_kinds[0].fields[1].depends_on == ("country",)


def test_provider_backed_options_require_choice_field() -> None:
    with pytest.raises(ValidationError, match="provider-backed options require a choice field"):
        SelectorField(
            name="country",
            label="Country",
            field_type=SelectorFieldType.TEXT,
            option_source=SelectorOptionSource.PROVIDER,
        )


def test_provider_backed_choice_rejects_static_choices() -> None:
    with pytest.raises(ValidationError, match="cannot declare static choices"):
        SelectorField(
            name="country",
            label="Country",
            field_type=SelectorFieldType.CHOICE,
            choices=("us",),
            option_source=SelectorOptionSource.PROVIDER,
        )


def test_selector_dependencies_must_refer_to_same_kind() -> None:
    with pytest.raises(ValidationError, match="same kind"):
        SelectorKind(
            kind="city",
            label="City",
            fields=(
                SelectorField(
                    name="city",
                    label="City",
                    field_type=SelectorFieldType.CHOICE,
                    option_source=SelectorOptionSource.PROVIDER,
                    depends_on=("country",),
                ),
            ),
        )


def test_selector_dependency_cycles_are_rejected() -> None:
    with pytest.raises(ValidationError, match="must not contain cycles"):
        SelectorKind(
            kind="location",
            label="Location",
            fields=(
                SelectorField(
                    name="country",
                    label="Country",
                    field_type=SelectorFieldType.CHOICE,
                    depends_on=("city",),
                ),
                SelectorField(
                    name="city",
                    label="City",
                    field_type=SelectorFieldType.CHOICE,
                    depends_on=("country",),
                ),
            ),
        )


def test_target_options_keep_value_separate_from_label() -> None:
    response = TargetOptions(
        provider="example",
        kind="country",
        field="country",
        options=(TargetOption(value="united_states", label="United States"),),
    )

    assert response.options[0].value == "united_states"
    assert response.options[0].label == "United States"


def test_provider_without_discovery_returns_controlled_error() -> None:
    provider = PlaceholderProvider()

    assert provider.capabilities.target_discovery is False
    with pytest.raises(ProviderError) as error:
        provider.target_options("country", "country", {})

    assert error.value.code == "UNSUPPORTED_TARGET_DISCOVERY"

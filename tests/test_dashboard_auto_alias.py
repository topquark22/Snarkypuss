"""Regression checks for automatically generated target aliases."""

from importlib.resources import files


def dashboard_script() -> str:
    return (
        files("snarkyctl")
        .joinpath("static", "dashboard.js")
        .read_text(encoding="utf-8")
    )


def test_new_destinations_generate_aliases_from_friendly_labels() -> None:
    script = dashboard_script()

    assert "const autoAliasTargets = new WeakSet();" in script
    assert "function normalizedAlias(value)" in script
    assert "function uniqueAlias(target, label)" in script
    assert "function updateAutoMetadata(target, kindSchema)" in script
    assert "autoAliasTargets.add(newDestinationDraft);" in script


def test_manual_alias_edit_disables_auto_aliasing() -> None:
    script = dashboard_script()

    assert "autoAliasTargets.delete(target);" in script


def test_auto_aliases_are_safe_unique_and_reserve_recommended() -> None:
    script = dashboard_script()

    assert 'const used = new Set(["recommended"]);' in script
    assert '.replace(/[^a-z0-9]+/g, "_")' in script
    assert 'const suffix = `_${sequence}`;' in script
    assert "32 - suffix.length" in script

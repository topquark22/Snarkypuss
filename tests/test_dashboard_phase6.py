"""Static regression checks for the generic cascading target editor."""

from importlib.resources import files


def dashboard_script() -> str:
    return (
        files("snarkyctl")
        .joinpath("static", "dashboard.js")
        .read_text(encoding="utf-8")
    )


def test_dashboard_uses_provider_neutral_target_option_discovery() -> None:
    script = dashboard_script()

    assert "/api/v3/admin/vpn/target-options?" in script
    assert 'field.option_source !== "provider"' in script
    assert "field.depends_on || []" in script
    assert "discoveryContext(target, field)" in script
    assert "nordvpn" not in script.casefold()


def test_dashboard_invalidates_and_reloads_dependent_fields() -> None:
    script = dashboard_script()

    assert "function clearDependentFields(" in script
    assert "clearDependentFields(target, kindSchema, field.name);" in script
    assert "states?.delete(field.name);" in script
    assert "void loadProviderOptions(" in script


def test_dashboard_autofills_new_labels_until_manually_edited() -> None:
    script = dashboard_script()

    assert "const autoLabelTargets = new WeakSet();" in script
    assert "function suggestedTargetLabel(" in script
    assert "updateAutoMetadata(target, kind);" in script
    assert "autoLabelTargets.delete(target);" in script


def test_dashboard_removes_unavailable_saved_destinations() -> None:
    script = dashboard_script()

    assert "const unavailableTargets = new Set();" in script
    assert "queueUnavailableTarget(target);" in script
    assert "async function cleanupUnavailableTargets()" in script
    assert "replaceCatalogueTargets(committedTargets)" in script
    assert "(no longer available)" not in script


def test_dashboard_refreshes_target_dropdown_from_committed_save() -> None:
    script = dashboard_script()

    assert "function populateTargetSelect(targets)" in script
    assert "await loadTargets();" in script
    assert "Catalogue saved." in script

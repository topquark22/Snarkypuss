"""Regression tests for the non-persisted recommended VPN target."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from snarkyctl.control.daemon import (
    BUILTIN_RECOMMENDED_ALIAS,
    BUILTIN_RECOMMENDED_LABEL,
    ControlService,
)
from snarkyctl.control.protocol import (
    ConnectRequest,
    Operation,
    PROTOCOL_VERSION,
    TargetCatalogGetRequest,
    TargetCatalogReplaceRequest,
    TargetsRequest,
)
from snarkyctl.providers.base import (
    ProviderCapabilities,
    ProviderError,
    VpnProvider,
    VpnSettings,
    VpnState,
    VpnStatus,
    VpnTarget,
)
from snarkyctl.targets.models import (
    ProviderTargetSchema,
    SelectorField,
    SelectorFieldType,
    SelectorKind,
    StoredTarget,
    TargetCatalogue,
)
from snarkyctl.targets.repository import MemoryTargetRepository

REQUEST_ID = UUID("0de2718e-98b1-43a0-879f-867d87b81a75")


class RecommendedProvider(VpnProvider):
    name = "fake"
    capabilities = ProviderCapabilities(
        connect=True,
        disconnect=True,
        target_selection=True,
        server_details=True,
        leak_protection_configuration=True,
    )

    def __init__(self) -> None:
        self.connected_target: StoredTarget | None = None

    def status(self) -> VpnStatus:
        return VpnStatus(state=VpnState.DISCONNECTED, provider=self.name)

    def settings(self) -> VpnSettings:
        return VpnSettings(
            provider=self.name,
            leak_protection_enabled=True,
            firewall_enabled=True,
        )

    def connect(self, target: VpnTarget) -> VpnStatus:
        del target
        raise AssertionError("structured targets must use connect_stored")

    def connect_stored(self, target: StoredTarget) -> VpnStatus:
        self.connected_target = target
        return VpnStatus(state=VpnState.CONNECTED, provider=self.name)

    def disconnect(self) -> VpnStatus:
        return VpnStatus(state=VpnState.DISCONNECTED, provider=self.name)

    def set_leak_protection(self, enabled: bool) -> VpnSettings:
        return VpnSettings(
            provider=self.name,
            leak_protection_enabled=enabled,
            firewall_enabled=True,
        )

    def target_schema(self) -> ProviderTargetSchema:
        return ProviderTargetSchema(
            provider=self.name,
            selector_kinds=(
                SelectorKind(kind="recommended", label="Fastest available server"),
                SelectorKind(
                    kind="server",
                    label="Specific server",
                    fields=(
                        SelectorField(
                            name="server",
                            label="Server",
                            field_type=SelectorFieldType.TEXT,
                            max_length=100,
                        ),
                    ),
                ),
            ),
        )

    def validate_selector(self, selector: dict[str, str | int | bool | None]) -> dict[str, str | int | bool | None]:
        if selector == {"kind": "recommended"}:
            return {"kind": "recommended"}
        if selector.get("kind") == "server" and isinstance(selector.get("server"), str):
            return dict(selector)
        raise ProviderError("INVALID_TARGET", "selector is invalid")


def control_service(
    repository: MemoryTargetRepository | None = None,
) -> tuple[ControlService, RecommendedProvider, MemoryTargetRepository]:
    provider = RecommendedProvider()
    repository = repository or MemoryTargetRepository()
    config = SimpleNamespace(
        settings=SimpleNamespace(
            status=SimpleNamespace(
                public_ip_url="https://api.ipify.org",
                public_ip_timeout_seconds=5,
            )
        ),
        targets=None,
    )
    service = ControlService(  # type: ignore[arg-type]
        config,
        provider,
        local_collector=lambda: (None, None, []),
        public_ip_collector=lambda _url, _timeout: SimpleNamespace(
            address="203.0.113.42",
            checked_at=datetime.now(UTC),
        ),
        target_repository=repository,
    )
    return service, provider, repository


def test_recommended_target_is_public_but_not_persisted() -> None:
    service, _provider, repository = control_service()

    public = service.dispatch(
        TargetsRequest(
            version=PROTOCOL_VERSION,
            request_id=REQUEST_ID,
            operation=Operation.TARGETS,
        )
    )
    editable = service.dispatch(
        TargetCatalogGetRequest(
            version=PROTOCOL_VERSION,
            request_id=REQUEST_ID,
            operation=Operation.TARGET_CATALOG_GET,
            provider="fake",
        )
    )

    assert public.success
    assert public.target_catalog is not None
    assert [(target.alias, target.label) for target in public.target_catalog.targets] == [
        (BUILTIN_RECOMMENDED_ALIAS, BUILTIN_RECOMMENDED_LABEL)
    ]
    assert editable.success
    assert editable.editable_target_catalogue is not None
    assert editable.editable_target_catalogue.targets == ()
    assert repository.get_catalogue("fake").targets == ()


def test_recommended_alias_connects_without_catalogue_row() -> None:
    service, provider, _repository = control_service()

    response = service.dispatch(
        ConnectRequest(
            version=PROTOCOL_VERSION,
            request_id=REQUEST_ID,
            operation=Operation.CONNECT,
            target=BUILTIN_RECOMMENDED_ALIAS,
        )
    )

    assert response.success
    assert provider.connected_target is not None
    assert provider.connected_target.alias == BUILTIN_RECOMMENDED_ALIAS
    assert provider.connected_target.selector == {"kind": "recommended"}
    assert response.vpn_status is not None
    assert response.vpn_status.target == BUILTIN_RECOMMENDED_ALIAS


def test_empty_editable_catalogue_is_allowed_with_builtin_recommended() -> None:
    repository = MemoryTargetRepository(
        (
            TargetCatalogue(
                provider="fake",
                revision=2,
                targets=(
                    StoredTarget(
                        alias="server1",
                        label="Server 1",
                        position=0,
                        selector={"kind": "server", "server": "server1"},
                    ),
                ),
            ),
        )
    )
    service, _provider, repository = control_service(repository)

    response = service.dispatch(
        TargetCatalogReplaceRequest(
            version=PROTOCOL_VERSION,
            request_id=REQUEST_ID,
            operation=Operation.TARGET_CATALOG_REPLACE,
            provider="fake",
            expected_revision=2,
            targets=(),
        )
    )

    assert response.success
    assert repository.get_catalogue("fake").targets == ()
    public = service.dispatch(
        TargetsRequest(
            version=PROTOCOL_VERSION,
            request_id=REQUEST_ID,
            operation=Operation.TARGETS,
        )
    )
    assert public.target_catalog is not None
    assert [target.alias for target in public.target_catalog.targets] == [
        BUILTIN_RECOMMENDED_ALIAS
    ]


@pytest.mark.parametrize(
    "target",
    [
        StoredTarget(
            alias="alahuakbar",
            label="Fastest available server",
            position=0,
            selector={"kind": "recommended"},
        ),
        StoredTarget(
            alias=BUILTIN_RECOMMENDED_ALIAS,
            label="Other target",
            position=0,
            selector={"kind": "server", "server": "server1"},
        ),
    ],
)
def test_catalogue_rejects_persisted_builtin_target(target: StoredTarget) -> None:
    service, _provider, repository = control_service()

    response = service.dispatch(
        TargetCatalogReplaceRequest(
            version=PROTOCOL_VERSION,
            request_id=REQUEST_ID,
            operation=Operation.TARGET_CATALOG_REPLACE,
            provider="fake",
            expected_revision=0,
            targets=(target,),
        )
    )

    assert not response.success
    assert response.error_code == "INVALID_CATALOG"
    assert repository.get_catalogue("fake").targets == ()

def test_legacy_persisted_recommended_target_is_filtered_and_removed_on_save() -> None:
    repository = MemoryTargetRepository(
        (
            TargetCatalogue(
                provider="fake",
                revision=4,
                targets=(
                    StoredTarget(
                        alias="alahuakbar",
                        label="Fastest available server",
                        position=0,
                        selector={"kind": "recommended"},
                    ),
                    StoredTarget(
                        alias="server1",
                        label="Server 1",
                        position=1,
                        selector={"kind": "server", "server": "server1"},
                    ),
                ),
            ),
        )
    )
    service, _provider, repository = control_service(repository)

    editable = service.dispatch(
        TargetCatalogGetRequest(
            version=PROTOCOL_VERSION,
            request_id=REQUEST_ID,
            operation=Operation.TARGET_CATALOG_GET,
            provider="fake",
        )
    )

    assert editable.success
    assert editable.editable_target_catalogue is not None
    assert [
        (target.alias, target.position)
        for target in editable.editable_target_catalogue.targets
    ] == [("server1", 0)]

    saved = service.dispatch(
        TargetCatalogReplaceRequest(
            version=PROTOCOL_VERSION,
            request_id=REQUEST_ID,
            operation=Operation.TARGET_CATALOG_REPLACE,
            provider="fake",
            expected_revision=4,
            targets=editable.editable_target_catalogue.targets,
        )
    )

    assert saved.success
    persisted = repository.get_catalogue("fake")
    assert persisted.revision == 5
    assert [target.alias for target in persisted.targets] == ["server1"]

"""Target repository contracts and non-SQLite implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from threading import Lock

from snarkyctl.providers.base import VpnTarget
from snarkyctl.targets.models import JsonObject, StoredTarget, TargetCatalogue


class RepositoryError(RuntimeError):
    """Stable target-storage failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class TargetRepository(ABC):
    """Persistence boundary for complete provider catalogues."""

    @abstractmethod
    def get_catalogue(self, provider: str) -> TargetCatalogue:
        """Return the provider catalogue or an empty revision-zero catalogue."""

    @abstractmethod
    def replace_catalogue(
        self,
        provider: str,
        expected_revision: int,
        targets: tuple[StoredTarget, ...],
    ) -> TargetCatalogue:
        """Atomically replace a catalogue using optimistic concurrency."""


class MemoryTargetRepository(TargetRepository):
    """Thread-safe repository for tests and transient use."""

    def __init__(self, catalogues: tuple[TargetCatalogue, ...] = ()) -> None:
        self._catalogues = {catalogue.provider: catalogue for catalogue in catalogues}
        self._lock = Lock()

    def get_catalogue(self, provider: str) -> TargetCatalogue:
        with self._lock:
            return self._catalogues.get(
                provider, TargetCatalogue(provider=provider, revision=0, targets=())
            )

    def replace_catalogue(
        self,
        provider: str,
        expected_revision: int,
        targets: tuple[StoredTarget, ...],
    ) -> TargetCatalogue:
        candidate = TargetCatalogue(provider=provider, revision=expected_revision + 1, targets=targets)
        with self._lock:
            current = self._catalogues.get(
                provider, TargetCatalogue(provider=provider, revision=0, targets=())
            )
            if current.revision != expected_revision:
                raise RepositoryError("CATALOG_CONFLICT", "Catalogue revision is stale.")
            self._catalogues[provider] = candidate
            return candidate


class YamlTargetRepository(TargetRepository):
    """Read-only bridge from the existing root-owned YAML catalogue."""

    def __init__(
        self,
        provider: str,
        targets: tuple[VpnTarget, ...],
        importer: Callable[[str], JsonObject],
    ) -> None:
        stored = tuple(
            StoredTarget(
                alias=target.alias,
                label=target.label,
                position=position,
                selector=importer(target.provider_target),
            )
            for position, target in enumerate(targets)
        )
        self._catalogue = TargetCatalogue(provider=provider, revision=0, targets=stored)

    def get_catalogue(self, provider: str) -> TargetCatalogue:
        if provider != self._catalogue.provider:
            return TargetCatalogue(provider=provider, revision=0, targets=())
        return self._catalogue

    def replace_catalogue(
        self,
        provider: str,
        expected_revision: int,
        targets: tuple[StoredTarget, ...],
    ) -> TargetCatalogue:
        del provider, expected_revision, targets
        raise RepositoryError(
            "READ_ONLY_REPOSITORY",
            "The compatibility YAML target catalogue is read-only.",
        )

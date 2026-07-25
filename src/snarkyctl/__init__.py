"""SnarkyCtl package metadata."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("snarkyctl")
except PackageNotFoundError:  # pragma: no cover - only used before installation
    # Allows commands to run directly from an uninstalled source checkout.
    __version__ = "0.10.0.dev2"

__all__ = ["__version__"]

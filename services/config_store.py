"""Simple in-memory store for PLC configuration metadata."""
from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Optional

from .assembly_config import AssemblyPathRegistry
from .config_loader import DeviceConfiguration

__all__ = ["ConfigurationStore", "ConfigurationState"]


@dataclass(frozen=True)
class ConfigurationState:
    """Snapshot of the currently loaded configuration."""

    configuration: Optional[DeviceConfiguration]
    registry: AssemblyPathRegistry

    @property
    def loaded(self) -> bool:
        return self.configuration is not None


class ConfigurationStore:
    """Thread-safe, in-memory storage for device configuration metadata."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._configuration: Optional[DeviceConfiguration] = None
        self._registry: AssemblyPathRegistry = AssemblyPathRegistry()

    def load(self, configuration: DeviceConfiguration) -> ConfigurationState:
        """Persist *configuration* and update the assembly registry."""

        with self._lock:
            self._configuration = configuration
            self._registry = configuration.build_registry()
            return ConfigurationState(configuration, self._registry)

    def clear(self) -> None:
        """Clear any loaded configuration data."""

        with self._lock:
            self._configuration = None
            self._registry = AssemblyPathRegistry()

    def get_state(self) -> ConfigurationState:
        with self._lock:
            return ConfigurationState(self._configuration, self._registry)

    def get_registry(self) -> AssemblyPathRegistry:
        with self._lock:
            return self._registry

    def get_configuration(self) -> Optional[DeviceConfiguration]:
        with self._lock:
            return self._configuration

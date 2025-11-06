"""Assembly configuration helpers built on top of :mod:`plc` primitives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping, MutableMapping, Optional, Tuple, Union

from cip import CIP_Path, CIP_ResponseStatus
from plc import NO_NETWORK, PLCClient, register_offline_fixture

__all__ = [
    "AssemblyConfigError",
    "AssemblyPathRegistry",
    "AssemblyConfigService",
    "AttributeSpec",
    "COMMON_ATTRIBUTE_SETS",
    "COMMON_ATTRIBUTE_SPECS",
    "DEFAULT_ASSEMBLY_ALIASES",
    "DEFAULT_OFFLINE_FIXTURES",
    "install_default_offline_fixtures",
]


class AssemblyConfigError(Exception):
    """Base exception for assembly configuration helpers."""


class AssemblyUpdateError(AssemblyConfigError):
    """Raised when a batch update fails for a specific attribute."""

    def __init__(self, attribute: str, status: Optional[int]):
        message = "Failed to write attribute '{}'".format(attribute)
        if status is not None:
            status_message = CIP_ResponseStatus.ERROR_CODES.get(
                status, "Unknown status 0x{:02x}".format(status)
            )
            message = "{} (status {}: {})".format(message, status, status_message)
        super(AssemblyUpdateError, self).__init__(message)
        self.attribute = attribute
        self.status = status


@dataclass(frozen=True)
class AttributeSpec:
    """Description of a CIP attribute commonly used for assemblies."""

    attribute_id: int
    size: Optional[int] = 2
    signed: bool = False

    def decode(self, payload: bytes):
        if self.size is None:
            return bytes(payload)
        expected = int(self.size)
        if len(payload) != expected:
            raise AssemblyConfigError(
                "Unexpected payload size for attribute 0x{:x}: expected {}, got {}".format(
                    self.attribute_id, expected, len(payload)
                )
            )
        return int.from_bytes(payload, byteorder="little", signed=self.signed)

    def encode(self, value) -> bytes:
        if self.size is None:
            if isinstance(value, (bytes, bytearray)):
                return bytes(value)
            raise AssemblyConfigError(
                "Attribute 0x{:x} expects raw bytes".format(self.attribute_id)
            )
        integer = int(value)
        return integer.to_bytes(self.size, byteorder="little", signed=self.signed)


COMMON_ATTRIBUTE_SPECS: Dict[str, AttributeSpec] = {
    "input_size": AttributeSpec(0x03, size=2),
    "output_size": AttributeSpec(0x04, size=2),
    "production_inhibit_time": AttributeSpec(0x09, size=2),
    "production_trigger": AttributeSpec(0x0B, size=1),
}

COMMON_ATTRIBUTE_SETS: Dict[str, Tuple[str, ...]] = {
    "io_sizes": ("input_size", "output_size"),
    "production": ("production_trigger", "production_inhibit_time"),
}

DEFAULT_ASSEMBLY_ALIASES: Dict[str, Tuple[int, int]] = {
    "inputs": (0x04, 0x64),
    "outputs": (0x04, 0x65),
    "configuration": (0x04, 0x66),
}

DEFAULT_OFFLINE_FIXTURES: Dict[Tuple[int, int], Dict[int, bytes]] = {
    (0x04, 0x64): {
        0x03: (16).to_bytes(2, "little"),
        0x04: (0).to_bytes(2, "little"),
        0x09: (10).to_bytes(2, "little"),
        0x0B: (1).to_bytes(1, "little"),
    },
    (0x04, 0x65): {
        0x03: (0).to_bytes(2, "little"),
        0x04: (16).to_bytes(2, "little"),
        0x09: (10).to_bytes(2, "little"),
        0x0B: (1).to_bytes(1, "little"),
    },
    (0x04, 0x66): {
        0x03: (4).to_bytes(2, "little"),
        0x04: (4).to_bytes(2, "little"),
        0x09: (5).to_bytes(2, "little"),
        0x0B: (2).to_bytes(1, "little"),
    },
}


def install_default_offline_fixtures(overwrite: bool = False) -> None:
    """Install canned fixtures that emulate assembly attributes offline."""

    for (class_id, instance_id), attrs in DEFAULT_OFFLINE_FIXTURES.items():
        register_offline_fixture(class_id, instance_id, attrs, overwrite=overwrite)


class AssemblyPathRegistry:
    """Translate human readable assembly identifiers into CIP paths."""

    def __init__(self, aliases: Optional[Mapping[str, Tuple[int, int]]] = None):
        self._aliases: Dict[str, Tuple[int, int]] = {}
        if aliases is None:
            aliases = DEFAULT_ASSEMBLY_ALIASES
        for name, (class_id, instance_id) in aliases.items():
            self.register(name, class_id, instance_id)

    def register(self, name: str, class_id: int, instance_id: int) -> None:
        key = name.strip().lower()
        self._aliases[key] = (int(class_id), int(instance_id))

    def resolve(self, identifier: Union[str, Tuple[int, int], CIP_Path]) -> Tuple[int, int]:
        if isinstance(identifier, CIP_Path):
            return self._from_path(identifier)
        if isinstance(identifier, (tuple, list)) and len(identifier) == 2:
            return int(identifier[0]), int(identifier[1])
        if isinstance(identifier, str):
            return self._from_string(identifier)
        raise AssemblyConfigError("Unsupported assembly identifier {!r}".format(identifier))

    def path_for(
        self, identifier: Union[str, Tuple[int, int], CIP_Path], attribute_id: Optional[int] = None
    ) -> CIP_Path:
        class_id, instance_id = self.resolve(identifier)
        if attribute_id is None:
            return CIP_Path.make(class_id=class_id, instance_id=instance_id)
        return CIP_Path.make(
            class_id=class_id, instance_id=instance_id, attribute_id=int(attribute_id)
        )

    def _from_string(self, identifier: str) -> Tuple[int, int]:
        token = identifier.strip().lower()
        if token in self._aliases:
            return self._aliases[token]
        if "/" in token:
            parts = token.split("/", 1)
        elif ":" in token:
            parts = token.split(":", 1)
        else:
            raise AssemblyConfigError("Unknown assembly alias '{}'".format(identifier))
        try:
            class_id = int(parts[0], 0)
            instance_id = int(parts[1], 0)
        except ValueError as exc:
            raise AssemblyConfigError("Invalid assembly identifier '{}'".format(identifier)) from exc
        return class_id, instance_id

    @staticmethod
    def _from_path(path: CIP_Path) -> Tuple[int, int]:
        class_id = None
        instance_id = None
        for seg_type, value in path.to_tuplelist():
            if seg_type == 0:
                class_id = value
            elif seg_type == 1:
                instance_id = value
        if class_id is None or instance_id is None:
            raise AssemblyConfigError("CIP path is missing class or instance information")
        return class_id, instance_id


class AssemblyConfigService:
    """High level helpers to fetch and update assembly attributes."""

    def __init__(
        self,
        client: PLCClient,
        registry: Optional[AssemblyPathRegistry] = None,
        specs: Optional[Mapping[str, AttributeSpec]] = None,
        attribute_sets: Optional[Mapping[str, Tuple[str, ...]]] = None,
    ):
        self._client = client
        self._registry = registry or AssemblyPathRegistry()
        self._specs: Dict[str, AttributeSpec] = dict(COMMON_ATTRIBUTE_SPECS)
        if specs:
            self._specs.update(specs)
        self._attribute_sets: Dict[str, Tuple[str, ...]] = dict(COMMON_ATTRIBUTE_SETS)
        if attribute_sets:
            self._attribute_sets.update(attribute_sets)

    def read_attribute(self, assembly: Union[str, Tuple[int, int], CIP_Path], name: str):
        spec = self._require_spec(name)
        class_id, instance_id = self._registry.resolve(assembly)
        payload = self._client.get_attribute(class_id, instance_id, spec.attribute_id)
        if payload is None:
            raise AssemblyConfigError(
                "Attribute '{}' (0x{:x}) unavailable for class {} instance {}".format(
                    name, spec.attribute_id, class_id, instance_id
                )
            )
        return spec.decode(payload)

    def read_attribute_set(
        self, assembly: Union[str, Tuple[int, int], CIP_Path], set_name: str
    ) -> Dict[str, object]:
        attributes = {}
        for name in self._require_attribute_set(set_name):
            attributes[name] = self.read_attribute(assembly, name)
        return attributes

    def write_attribute(self, assembly, name: str, value) -> int:
        spec = self._require_spec(name)
        class_id, instance_id = self._registry.resolve(assembly)
        payload = spec.encode(value)
        status = self._client.set_attribute(class_id, instance_id, spec.attribute_id, payload)
        if status is None or status != 0:
            raise AssemblyUpdateError(name, status)
        return status

    def update_attributes(
        self,
        assembly,
        values: Mapping[str, object],
        rollback_on_partial: bool = True,
    ) -> Dict[str, object]:
        if not values:
            return {}
        class_id, instance_id = self._registry.resolve(assembly)
        specs: MutableMapping[str, AttributeSpec] = {}
        originals: Dict[str, bytes] = {}
        for name in values:
            spec = self._require_spec(name)
            specs[name] = spec
            payload = self._client.get_attribute(class_id, instance_id, spec.attribute_id)
            if payload is None:
                raise AssemblyConfigError(
                    "Attribute '{}' (0x{:x}) unavailable for class {} instance {}".format(
                        name, spec.attribute_id, class_id, instance_id
                    )
                )
            originals[name] = bytes(payload)

        applied: List[str] = []
        results: Dict[str, object] = {}
        partial_code = 0x06  # CIP_ResponseStatus partial transfer
        for name in values:
            spec = specs[name]
            payload = spec.encode(values[name])
            status = self._client.set_attribute(class_id, instance_id, spec.attribute_id, payload)
            if status is None or status != 0:
                if rollback_on_partial and status == partial_code:
                    for applied_name in reversed(applied):
                        original_payload = originals[applied_name]
                        original_spec = specs[applied_name]
                        self._client.set_attribute(
                            class_id, instance_id, original_spec.attribute_id, original_payload
                        )
                raise AssemblyUpdateError(name, status)
            results[name] = spec.decode(payload)
            applied.append(name)
        return results

    def _require_spec(self, name: str) -> AttributeSpec:
        try:
            return self._specs[name]
        except KeyError as exc:
            raise AssemblyConfigError("Unknown attribute '{}'".format(name)) from exc

    def _require_attribute_set(self, set_name: str) -> Tuple[str, ...]:
        try:
            return self._attribute_sets[set_name]
        except KeyError as exc:
            raise AssemblyConfigError("Unknown attribute set '{}'".format(set_name)) from exc


if NO_NETWORK:
    install_default_offline_fixtures(overwrite=False)

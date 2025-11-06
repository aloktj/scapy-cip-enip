"""Utilities to parse PLC configuration XML documents."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
import xml.etree.ElementTree as ET

from cip import CIP_Path

from .assembly_config import AssemblyPathRegistry, DEFAULT_ASSEMBLY_ALIASES

__all__ = [
    "ConfigurationError",
    "ConfigurationParseError",
    "ConfigurationValidationError",
    "DeviceIdentity",
    "AssemblyMember",
    "AssemblyDefinition",
    "DeviceConfiguration",
    "load_configuration",
]


class ConfigurationError(Exception):
    """Base exception raised for configuration related failures."""


class ConfigurationParseError(ConfigurationError):
    """Raised when the XML payload cannot be parsed."""


class ConfigurationValidationError(ConfigurationError):
    """Raised when the configuration document fails semantic validation."""


@dataclass(frozen=True)
class DeviceIdentity:
    """Metadata describing the identity of the target PLC device."""

    name: Optional[str] = None
    vendor: Optional[str] = None
    product_code: Optional[str] = None
    revision: Optional[str] = None
    serial_number: Optional[str] = None


@dataclass(frozen=True)
class AssemblyMember:
    """Metadata describing a member within an assembly."""

    name: str
    datatype: Optional[str] = None
    direction: Optional[str] = None
    offset: Optional[int] = None
    size: Optional[int] = None
    description: Optional[str] = None


@dataclass(frozen=True)
class AssemblyDefinition:
    """Description of an assembly declared in the configuration file."""

    alias: str
    class_id: int
    instance_id: int
    direction: str
    size: Optional[int]
    members: Tuple[AssemblyMember, ...]

    def to_cip_path(self, attribute_id: Optional[int] = None) -> CIP_Path:
        """Return a :class:`cip.CIP_Path` instance for the assembly."""

        params = {
            "class_id": self.class_id,
            "instance_id": self.instance_id,
        }
        if attribute_id is not None:
            params["attribute_id"] = attribute_id
        return CIP_Path.make(**params)


@dataclass(frozen=True)
class DeviceConfiguration:
    """Container for the parsed configuration metadata."""

    identity: DeviceIdentity
    assemblies: Tuple[AssemblyDefinition, ...]

    def alias_mapping(self, include_defaults: bool = True) -> Mapping[str, Tuple[int, int]]:
        aliases: Dict[str, Tuple[int, int]] = {}
        if include_defaults:
            aliases.update(DEFAULT_ASSEMBLY_ALIASES)
        for assembly in self.assemblies:
            aliases[assembly.alias.lower()] = (assembly.class_id, assembly.instance_id)
        return aliases

    def build_registry(self, include_defaults: bool = True) -> AssemblyPathRegistry:
        return AssemblyPathRegistry(aliases=self.alias_mapping(include_defaults=include_defaults))


def load_configuration(xml_payload: str | bytes) -> DeviceConfiguration:
    """Parse *xml_payload* into a :class:`DeviceConfiguration`."""

    try:
        root = ET.fromstring(xml_payload)
    except ET.ParseError as exc:
        raise ConfigurationParseError("Malformed XML payload") from exc

    if root.tag.lower() not in {"device", "deviceconfiguration", "plc"}:
        raise ConfigurationValidationError(
            "Root element must be <Device>, <DeviceConfiguration>, or <Plc>"
        )

    identity = _parse_identity(root.find("Identity"))
    assemblies = _parse_assemblies(root.findall("Assemblies/Assembly"))
    if not assemblies:
        assemblies = _parse_assemblies(root.findall("Assembly"))

    return DeviceConfiguration(identity=identity, assemblies=tuple(assemblies))


def _parse_identity(node: Optional[ET.Element]) -> DeviceIdentity:
    if node is None:
        return DeviceIdentity()
    attrs = node.attrib
    return DeviceIdentity(
        name=attrs.get("name") or _text_if_present(node.find("Name")),
        vendor=attrs.get("vendor") or _text_if_present(node.find("Vendor")),
        product_code=attrs.get("product") or _text_if_present(node.find("Product")),
        revision=attrs.get("revision") or _text_if_present(node.find("Revision")),
        serial_number=attrs.get("serial") or _text_if_present(node.find("SerialNumber")),
    )


def _parse_assemblies(nodes: Sequence[ET.Element]) -> List[AssemblyDefinition]:
    assemblies: List[AssemblyDefinition] = []
    aliases: Dict[str, ET.Element] = {}
    for node in nodes:
        alias = _require_attr(node, "alias")
        token = alias.strip().lower()
        if token in aliases:
            raise ConfigurationValidationError(f"Duplicate assembly alias '{alias}'")
        class_id = _parse_int(_require_attr(node, "class_id"))
        instance_id = _parse_int(_require_attr(node, "instance_id"))
        direction = _require_attr(node, "direction").strip().lower()
        if direction == "config":
            direction = "configuration"
        if direction not in {"input", "output", "configuration", "bidirectional"}:
            raise ConfigurationValidationError(
                f"Assembly '{alias}' has unsupported direction '{direction}'"
            )
        size = _parse_optional_int(node.attrib.get("size"))
        members = _parse_members(node.findall("Member"))
        assemblies.append(
            AssemblyDefinition(
                alias=alias,
                class_id=class_id,
                instance_id=instance_id,
                direction=direction,
                size=size,
                members=tuple(members),
            )
        )
        aliases[token] = node
    return assemblies


def _parse_members(nodes: Iterable[ET.Element]) -> List[AssemblyMember]:
    members: List[AssemblyMember] = []
    for node in nodes:
        name = _require_attr(node, "name")
        members.append(
            AssemblyMember(
                name=name,
                datatype=node.attrib.get("datatype"),
                direction=node.attrib.get("direction"),
                offset=_parse_optional_int(node.attrib.get("offset")),
                size=_parse_optional_int(node.attrib.get("size")),
                description=node.attrib.get("description") or node.text,
            )
        )
    return members


def _require_attr(node: ET.Element, name: str) -> str:
    value = node.attrib.get(name)
    if value is None or not value.strip():
        raise ConfigurationValidationError(
            f"Element <{node.tag}> is missing required attribute '{name}'"
        )
    return value


def _parse_int(value: str) -> int:
    try:
        return int(value, 0)
    except ValueError as exc:
        raise ConfigurationValidationError(f"Invalid integer value '{value}'") from exc


def _parse_optional_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    return _parse_int(value)


def _text_if_present(node: Optional[ET.Element]) -> Optional[str]:
    if node is None:
        return None
    text = node.text or ""
    return text.strip() or None

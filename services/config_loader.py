"""Utilities to parse PLC configuration XML documents."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple
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

    if root.tag.lower() not in {"device", "deviceconfiguration", "plc", "cip"}:
        raise ConfigurationValidationError(
            "Root element must be <Device>, <DeviceConfiguration>, <Plc>, or <Cip>"
        )

    identity = _parse_identity(_find_child(root, "Identity"))

    assembly_nodes = [
        element
        for element in root.iter()
        if _normalize_key(element.tag) == "assembly"
    ]
    assemblies = _parse_assemblies(assembly_nodes)

    return DeviceConfiguration(identity=identity, assemblies=tuple(assemblies))


def _parse_identity(node: Optional[ET.Element]) -> DeviceIdentity:
    if node is None:
        return DeviceIdentity()
    attrs = _normalize_attributes(node)
    name = _get_attr(attrs, "name", "product_name")
    if name is None:
        name = _text_if_present(_find_child(node, "Name", "ProductName"))
    vendor = _get_attr(attrs, "vendor", "vendor_id", "vendor_name")
    if vendor is None:
        vendor = _text_if_present(_find_child(node, "Vendor", "VendorName"))
    product_code = _get_attr(attrs, "product", "product_code")
    if product_code is None:
        product_code = _text_if_present(_find_child(node, "Product", "ProductCode"))
    revision = _get_attr(attrs, "revision")
    if revision is None:
        major = _get_attr(attrs, "revision_major")
        minor = _get_attr(attrs, "revision_minor")
        if major and minor:
            revision = f"{major}.{minor}"
        else:
            revision = _text_if_present(
                _find_child(node, "Revision", "RevisionMajor", "RevisionMinor")
            )
    serial_number = _get_attr(attrs, "serial", "serial_number")
    if serial_number is None:
        serial_number = _text_if_present(
            _find_child(node, "SerialNumber", "Serial", "SerialNo")
        )
    return DeviceIdentity(
        name=name,
        vendor=vendor,
        product_code=product_code,
        revision=revision,
        serial_number=serial_number,
    )


def _parse_assemblies(nodes: Sequence[ET.Element]) -> List[AssemblyDefinition]:
    assemblies: List[AssemblyDefinition] = []
    aliases: Dict[str, ET.Element] = {}
    for node in nodes:
        attrs = _normalize_attributes(node)
        alias = _get_attr(attrs, "alias", "id", "name")
        if alias is None:
            alias_node = _find_child(node, "Name")
            alias = _text_if_present(alias_node)
        if not alias:
            raise ConfigurationValidationError(
                f"Element <{node.tag}> is missing required attribute 'alias'"
            )
        token = alias.strip().lower()
        if token in aliases:
            raise ConfigurationValidationError(f"Duplicate assembly alias '{alias}'")
        class_id_str = _get_attr(attrs, "class_id", "classid", "class")
        if class_id_str is None:
            class_id = 0x04
        else:
            class_id = _parse_int(class_id_str)
        instance_id_str = _get_attr(attrs, "instance_id", "instanceid", "instance")
        if instance_id_str is None:
            raise ConfigurationValidationError(
                f"Assembly '{alias}' is missing required instance identifier"
            )
        instance_id = _parse_int(instance_id_str)
        direction_raw = _get_attr(attrs, "direction", "dir")
        if direction_raw is None:
            raise ConfigurationValidationError(
                f"Assembly '{alias}' is missing required direction"
            )
        direction = direction_raw.strip().lower()
        if direction == "config":
            direction = "configuration"
        elif direction == "in":
            direction = "input"
        elif direction == "out":
            direction = "output"
        elif direction in {"inout", "io"}:
            direction = "bidirectional"
        if direction not in {"input", "output", "configuration", "bidirectional"}:
            raise ConfigurationValidationError(
                f"Assembly '{alias}' has unsupported direction '{direction}'"
            )
        size = _parse_optional_int(_get_attr(attrs, "size", "length", "bytelength"))
        members = _parse_members(node)
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


def _parse_members(node: ET.Element) -> List[AssemblyMember]:
    explicit_member_nodes = _collect_member_nodes(node)
    if explicit_member_nodes:
        return _parse_member_elements(explicit_member_nodes)
    return _parse_scalar_members(node)


def _collect_member_nodes(node: ET.Element) -> List[ET.Element]:
    collected: List[ET.Element] = []
    for child in node:
        if _normalize_key(child.tag) == "member":
            collected.append(child)
        elif _normalize_key(child.tag) == "members":
            collected.extend(
                grandchild
                for grandchild in child
                if _normalize_key(grandchild.tag) == "member"
            )
    return collected


def _parse_member_elements(nodes: Iterable[ET.Element]) -> List[AssemblyMember]:
    members: List[AssemblyMember] = []
    for node in nodes:
        attrs = _normalize_attributes(node)
        scalar = _find_first_scalar(node)
        name = _get_attr(attrs, "name", "symbol", "symbol_name", "symbolname", "id")
        if not name and scalar is not None:
            name = _get_attr(
                _normalize_attributes(scalar),
                "name",
                "symbol",
                "symbol_name",
                "symbolname",
                "id",
            )
        if not name:
            raise ConfigurationValidationError(
                f"Element <{node.tag}> is missing required attribute 'name'"
            )
        datatype = _get_attr(attrs, "datatype")
        if datatype is None and scalar is not None:
            datatype = scalar.tag.lower()
        direction = _get_attr(attrs, "direction")
        offset = _parse_optional_int(
            _get_attr(attrs, "offset", "byte_offset", "byteoffset")
        )
        if offset is None and scalar is not None:
            offset = _parse_optional_int(
                _get_attr(_normalize_attributes(scalar), "offset", "byte_offset", "byteoffset")
            )
        size = _parse_optional_int(
            _get_attr(attrs, "size", "length", "byte_length", "bytelength")
        )
        if size is None and scalar is not None:
            size = _parse_optional_int(
                _get_attr(
                    _normalize_attributes(scalar),
                    "size",
                    "length",
                    "byte_length",
                    "bytelength",
                )
            )
        if size is None and scalar is not None:
            size = _default_size_for_type(scalar.tag)
        description = _get_attr(attrs, "description", "comment")
        if description is None and scalar is not None:
            description = _get_attr(
                _normalize_attributes(scalar), "description", "comment"
            )
        if description is None and node.text and node.text.strip():
            description = node.text.strip()
        if description is None and scalar is not None and scalar.text and scalar.text.strip():
            description = scalar.text.strip()
        members.append(
            AssemblyMember(
                name=name,
                datatype=datatype,
                direction=direction,
                offset=offset,
                size=size,
                description=description,
            )
        )
    return members


def _parse_scalar_members(node: ET.Element) -> List[AssemblyMember]:
    members: List[AssemblyMember] = []
    for index, scalar in enumerate(_iter_scalar_elements(node)):
        attrs = _normalize_attributes(scalar)
        name = _get_attr(attrs, "name", "symbol", "symbol_name", "symbolname", "id")
        if not name:
            name = f"{scalar.tag}_{index}"
        datatype = scalar.tag.lower()
        offset = _parse_optional_int(
            _get_attr(attrs, "offset", "byte_offset", "byteoffset")
        )
        size = _parse_optional_int(
            _get_attr(attrs, "size", "length", "byte_length", "bytelength")
        )
        if size is None:
            bits = _parse_optional_int(_get_attr(attrs, "bit_length", "bits"))
            if bits is not None and bits % 8 == 0:
                size = bits // 8
        if size is None:
            size = _default_size_for_type(scalar.tag)
        description = _get_attr(attrs, "description", "comment")
        if description is None and scalar.text and scalar.text.strip():
            description = scalar.text.strip()
        members.append(
            AssemblyMember(
                name=name,
                datatype=datatype,
                direction=None,
                offset=offset,
                size=size,
                description=description,
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


def _normalize_key(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _normalize_attributes(node: ET.Element) -> Dict[str, str]:
    return {
        _normalize_key(key): val
        for key, val in node.attrib.items()
        if val is not None and str(val).strip()
    }


def _get_attr(attrs: Mapping[str, str], *candidates: str) -> Optional[str]:
    for candidate in candidates:
        token = _normalize_key(candidate)
        value = attrs.get(token)
        if value is not None and str(value).strip():
            return value
    return None


def _find_child(node: ET.Element, *names: str) -> Optional[ET.Element]:
    if not names:
        return None
    targets = {_normalize_key(name) for name in names}
    for child in node:
        if _normalize_key(child.tag) in targets:
            return child
    return None


def _iter_scalar_elements(node: ET.Element) -> Iterator[ET.Element]:
    for child in node:
        key = _normalize_key(child.tag)
        if key == "member":
            scalar = _find_first_scalar(child)
            if scalar is not None:
                yield scalar
        elif key in {"members", "structure", "struct", "data"}:
            yield from _iter_scalar_elements(child)
        elif key in _SCALAR_TYPE_SIZES:
            yield child
        else:
            # Continue searching nested containers for scalar definitions
            yield from _iter_scalar_elements(child)


def _find_first_scalar(node: ET.Element) -> Optional[ET.Element]:
    for child in node:
        if _normalize_key(child.tag) in _SCALAR_TYPE_SIZES:
            return child
        nested = _find_first_scalar(child)
        if nested is not None:
            return nested
    return None


def _default_size_for_type(tag: str) -> Optional[int]:
    return _SCALAR_TYPE_SIZES.get(_normalize_key(tag))


_SCALAR_TYPE_SIZES: Dict[str, Optional[int]] = {
    "bool": 1,
    "boolean": 1,
    "byte": 1,
    "sint": 1,
    "usint": 1,
    "int": 2,
    "uint": 2,
    "word": 2,
    "dint": 4,
    "udint": 4,
    "dword": 4,
    "lint": 8,
    "ulint": 8,
    "lword": 8,
    "real": 4,
    "lreal": 8,
    "shortstring": None,
    "string": None,
}


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

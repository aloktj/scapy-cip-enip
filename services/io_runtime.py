"""Runtime helpers for polling and producing I/O assemblies.

This module centralises the coordination logic required to keep assembly
payloads synchronised with a PLC session.  It consumes the parsed
configuration metadata, tracks assembly sizes and directions, and provides
helper methods that interact with :class:`services.plc_manager.PLCManager`
for reads and :class:`plc.PLCClient` for unit-data writes.
"""
from __future__ import annotations

import binascii
import struct
import threading
import time
from dataclasses import dataclass, field
from queue import Empty, Queue
from typing import Dict, Iterable, Optional, Tuple

from scapy import all as scapy_all

from cip import CIP
from .config_loader import AssemblyDefinition, AssemblyMember, DeviceConfiguration
from .plc_manager import (
    CIPStatus,
    PLCConnectionError,
    PLCResponseError,
    PLCManager,
)
from plc import PLCClient

__all__ = [
    "AssemblyDirectionError",
    "AssemblyMemberValue",
    "AssemblyNotRegisteredError",
    "AssemblyRuntimeError",
    "AssemblyRuntimeView",
    "IORuntime",
    "OutputRequest",
]


class AssemblyRuntimeError(Exception):
    """Base exception raised for IO runtime failures."""


class AssemblyNotRegisteredError(AssemblyRuntimeError):
    """Raised when referencing an assembly that has not been configured."""


class AssemblyDirectionError(AssemblyRuntimeError):
    """Raised when an operation is incompatible with the assembly direction."""


@dataclass(frozen=True)
class AssemblyMemberValue:
    """Decoded representation of an assembly member payload."""

    name: str
    offset: Optional[int]
    size: Optional[int]
    datatype: Optional[str]
    description: Optional[str]
    raw_hex: str
    int_value: Optional[int]


@dataclass(frozen=True)
class AssemblyRuntimeView:
    """Snapshot of the runtime state associated with an assembly."""

    alias: str
    class_id: int
    instance_id: int
    direction: str
    size: Optional[int]
    payload: bytes
    timestamp: Optional[float]
    status: CIPStatus
    word_values: Tuple[int, ...]
    members: Tuple[AssemblyMemberValue, ...]


@dataclass
class OutputRequest:
    """Represents a pending unit-data write for an output assembly."""

    payload: bytes
    event: threading.Event = field(default_factory=threading.Event, repr=False)
    status: Optional[CIPStatus] = None
    error: Optional[Exception] = None

    def complete(self, status: CIPStatus, error: Optional[Exception] = None) -> None:
        self.status = status
        self.error = error
        self.event.set()

    def wait(self, timeout: Optional[float] = None) -> CIPStatus:
        if not self.event.wait(timeout):
            raise TimeoutError("Timed out waiting for output assembly write to complete")
        if self.error is not None:
            raise self.error
        return self.status or CIPStatus()


@dataclass
class _AssemblyRuntimeRecord:
    alias: str
    definition: AssemblyDefinition
    direction: str
    size: Optional[int]
    last_payload: bytes = b""
    last_timestamp: Optional[float] = None
    last_status: CIPStatus = field(default_factory=CIPStatus)
    word_values: Tuple[int, ...] = field(default_factory=tuple)
    member_values: Tuple[AssemblyMemberValue, ...] = field(default_factory=tuple)
    pending_outputs: Queue[OutputRequest] = field(default_factory=Queue, repr=False)

    def path(self):
        return self.definition.to_cip_path()


class IORuntime:
    """Keep assembly payloads synchronised with the PLC runtime."""

    def __init__(self) -> None:
        self._configuration: Optional[DeviceConfiguration] = None
        self._assemblies: Dict[str, _AssemblyRuntimeRecord] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Configuration management
    # ------------------------------------------------------------------
    def load(self, configuration: DeviceConfiguration) -> None:
        """Register assemblies declared in *configuration*."""

        assemblies: Dict[str, _AssemblyRuntimeRecord] = {}
        for definition in configuration.assemblies:
            key = self._normalise_alias(definition.alias)
            assemblies[key] = _AssemblyRuntimeRecord(
                alias=definition.alias,
                definition=definition,
                direction=definition.direction,
                size=definition.size,
            )

        with self._lock:
            self._configuration = configuration
            self._assemblies = assemblies

    def clear(self) -> None:
        """Clear any registered runtime state."""

        with self._lock:
            self._configuration = None
            self._assemblies = {}

    @property
    def configured(self) -> bool:
        return self._configuration is not None and bool(self._assemblies)

    # ------------------------------------------------------------------
    # Assembly enumeration helpers
    # ------------------------------------------------------------------
    def assemblies(self) -> Iterable[str]:
        with self._lock:
            return list(self._assemblies.keys())

    def input_assemblies(self) -> Iterable[str]:
        return self._assemblies_by_direction({"input", "bidirectional"})

    def output_assemblies(self) -> Iterable[str]:
        return self._assemblies_by_direction({"output", "bidirectional"})

    def _assemblies_by_direction(self, directions: set[str]) -> Iterable[str]:
        with self._lock:
            return [
                alias
                for alias, record in self._assemblies.items()
                if record.direction in directions
            ]

    # ------------------------------------------------------------------
    # Runtime snapshot helpers
    # ------------------------------------------------------------------
    def get_view(self, alias: str) -> AssemblyRuntimeView:
        record = self._get_record(alias)
        with self._lock:
            payload = record.last_payload
            timestamp = record.last_timestamp
            status = record.last_status
            words = record.word_values
            members = record.member_values
            definition = record.definition
        return AssemblyRuntimeView(
            alias=definition.alias,
            class_id=definition.class_id,
            instance_id=definition.instance_id,
            direction=record.direction,
            size=record.size,
            payload=payload,
            timestamp=timestamp,
            status=status,
            word_values=words,
            members=members,
        )

    # ------------------------------------------------------------------
    # PLC interaction helpers
    # ------------------------------------------------------------------
    def fetch(self, manager: PLCManager, client: PLCClient, alias: str) -> Tuple[bytes, CIPStatus]:
        """Fetch the full payload for *alias* using :meth:`PLCManager._read_full_tag`."""

        record = self._get_record(alias)
        if record.size is None:
            raise AssemblyRuntimeError(
                f"Assembly '{record.alias}' does not define a payload size and cannot be read"
            )

        try:
            data, status = manager._read_full_tag(
                client, record.definition.class_id, record.definition.instance_id, record.size
            )
        except PLCResponseError as exc:
            self._update_status(record, exc.status or CIPStatus())
            raise

        self._update_record(record, data, status)
        return data, status

    def queue_output(self, alias: str, payload: bytes) -> OutputRequest:
        record = self._get_record(alias)
        if record.direction not in {"output", "bidirectional"}:
            raise AssemblyDirectionError(
                f"Assembly '{record.alias}' is not configured for output operations"
            )
        if record.size is not None and len(payload) != record.size:
            raise AssemblyRuntimeError(
                f"Payload for assembly '{record.alias}' must be exactly {record.size} bytes"
            )
        request = OutputRequest(payload=bytes(payload))
        record.pending_outputs.put(request)
        return request

    def await_output(self, alias: str, timeout: Optional[float] = None) -> OutputRequest:
        record = self._get_record(alias)
        if record.direction not in {"output", "bidirectional"}:
            raise AssemblyDirectionError(
                f"Assembly '{record.alias}' is not configured for output operations"
            )
        try:
            return record.pending_outputs.get(timeout=timeout)
        except Empty as exc:
            raise exc

    def send_output(self, client: PLCClient, alias: str, payload: bytes) -> CIPStatus:
        record = self._get_record(alias)
        if record.direction not in {"output", "bidirectional"}:
            raise AssemblyDirectionError(
                f"Assembly '{record.alias}' is not configured for output operations"
            )
        if record.size is not None and len(payload) != record.size:
            raise AssemblyRuntimeError(
                f"Payload for assembly '{record.alias}' must be exactly {record.size} bytes"
            )

        cippkt = CIP(service=0x4D, path=record.definition.to_cip_path())
        if payload:
            cippkt /= scapy_all.Raw(load=payload)
        client.send_unit_cip(cippkt)
        try:
            response = client.recv_enippkt()
        except PLCConnectionError as exc:
            raise PLCConnectionError(
                "Socket closed while awaiting assembly write response"
            ) from exc
        if response is None:
            raise PLCResponseError("No response received for assembly write")
        cip_layer = response[CIP]
        status_code = int(cip_layer.status[0].status)
        status = CIPStatus.from_code(status_code)
        if status.code not in (0, None):
            raise PLCResponseError(
                f"Failed to write assembly '{record.alias}': {status.message}", status=status
            )
        self._update_record(record, payload, status)
        return status

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _normalise_alias(self, alias: str) -> str:
        return alias.strip().lower()

    def _get_record(self, alias: str) -> _AssemblyRuntimeRecord:
        key = self._normalise_alias(alias)
        with self._lock:
            record = self._assemblies.get(key)
        if record is None:
            raise AssemblyNotRegisteredError(f"Assembly '{alias}' is not registered in the runtime")
        return record

    def _update_record(
        self, record: _AssemblyRuntimeRecord, payload: bytes, status: CIPStatus
    ) -> None:
        timestamp = time.time()
        members = self._decode_members(record.definition.members, payload)
        words = self._decode_words(payload)
        with self._lock:
            record.last_payload = bytes(payload)
            record.last_timestamp = timestamp
            record.last_status = status
            record.member_values = members
            record.word_values = words

    def _update_status(self, record: _AssemblyRuntimeRecord, status: CIPStatus) -> None:
        with self._lock:
            record.last_status = status
            record.last_timestamp = time.time()

    def _decode_words(self, payload: bytes) -> Tuple[int, ...]:
        if not payload or len(payload) % 2:
            return tuple()
        try:
            return struct.unpack("<{}H".format(len(payload) // 2), payload)
        except struct.error:
            return tuple()

    def _decode_members(
        self, members: Tuple[AssemblyMember, ...], payload: bytes
    ) -> Tuple[AssemblyMemberValue, ...]:
        decoded = []
        for member in members:
            if member.offset is None or member.size is None:
                continue
            start = int(member.offset)
            end = start + int(member.size)
            if end > len(payload):
                continue
            chunk = payload[start:end]
            hex_value = binascii.hexlify(chunk).decode("ascii") if chunk else ""
            int_value: Optional[int] = None
            if chunk and member.size in (1, 2, 4):
                int_value = int.from_bytes(chunk, byteorder="little")
            decoded.append(
                AssemblyMemberValue(
                    name=member.name,
                    offset=member.offset,
                    size=member.size,
                    datatype=member.datatype,
                    description=member.description,
                    raw_hex=hex_value,
                    int_value=int_value,
                )
            )
        return tuple(decoded)

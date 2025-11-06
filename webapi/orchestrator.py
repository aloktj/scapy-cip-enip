"""Session orchestration helpers bridging the PLC manager and web API."""
from __future__ import annotations

import struct
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Literal

from scapy import all as scapy_all

from cip import CIP, CIP_Path
from services.plc_manager import (
    AssemblySnapshot,
    CIPStatus,
    ConnectionStatus,
    PLCManager,
    PLCManagerError,
    PLCResponseError,
)
from plc import PLCClient

__all__ = ["CommandResult", "SessionHandle", "SessionOrchestrator"]


@dataclass
class SessionHandle:
    """Representation of a PLC session managed by the orchestrator."""

    session_id: str
    client: PLCClient
    status: ConnectionStatus
    created_at: float = field(default_factory=time.time)


@dataclass
class CommandResult:
    """Result of a low level CIP command execution."""

    status: CIPStatus
    payload: bytes = b""


class SessionOrchestrator:
    """Coordinate PLC sessions that are shared across API requests."""

    def __init__(self, manager: PLCManager):
        self._manager = manager
        self._sessions: Dict[str, SessionHandle] = {}
        self._lock = threading.Lock()

    def start_session(self) -> SessionHandle:
        """Start a new PLC session and keep it active until explicitly stopped."""
        client = self._manager._pool.acquire()  # type: ignore[attr-defined]
        try:
            status = self._manager.start_session(client)
        except Exception:
            self._manager._pool.release(client)  # type: ignore[attr-defined]
            raise

        session_id = uuid.uuid4().hex
        handle = SessionHandle(session_id=session_id, client=client, status=status)
        with self._lock:
            self._sessions[session_id] = handle
        return handle

    def stop_session(self, session_id: str) -> ConnectionStatus:
        handle = self._require_session(session_id)
        try:
            status = self._manager.stop_session(handle.client)
        finally:
            self._manager._pool.release(handle.client)  # type: ignore[attr-defined]
            with self._lock:
                self._sessions.pop(session_id, None)
        handle.status.last_status = status
        handle.status.connected = False
        return handle.status

    def read_assembly(self, session_id: str, class_id: int, instance_id: int, total_size: int) -> AssemblySnapshot:
        handle = self._require_session(session_id)
        data, status = self._manager._read_full_tag(handle.client, class_id, instance_id, total_size)
        handle.status.last_status = status
        return AssemblySnapshot(
            class_id=class_id,
            instance_id=instance_id,
            data=data,
            timestamp=time.time(),
            last_status=status,
        )

    def write_attribute(
        self,
        session_id: str,
        path: CIP_Path,
        attribute_id: int,
        value: bytes,
    ) -> CIPStatus:
        handle = self._require_session(session_id)
        payload = scapy_all.Raw(load=struct.pack("<HH", 1, attribute_id) + value)
        cippkt = CIP(service=4, path=path) / payload
        handle.client.send_rr_cm_cip(cippkt)
        response = handle.client.recv_enippkt()
        if response is None:
            raise PLCResponseError("No response received for attribute write")
        cip_resp = response[CIP]
        status_code = int(cip_resp.status[0].status)
        status = CIPStatus.from_code(status_code)
        handle.status.last_status = status
        if status_code not in (0, None):
            raise PLCResponseError(
                "Failed to write attribute: {}".format(status.message),
                status=status,
            )
        return status

    def send_command(
        self,
        session_id: str,
        service: int,
        path: CIP_Path,
        payload: bytes,
        transport: Literal["rr", "rr_cm", "rr_mr", "unit"] = "rr_cm",
    ) -> CommandResult:
        handle = self._require_session(session_id)
        cippkt = CIP(service=service, path=path)
        if payload:
            cippkt /= scapy_all.Raw(load=payload)
        sender = self._resolve_sender(handle.client, transport)
        sender(cippkt)
        response = handle.client.recv_enippkt()
        if response is None:
            raise PLCResponseError("No response received for command")
        cip_resp = response[CIP]
        status_code = int(cip_resp.status[0].status)
        status = CIPStatus.from_code(status_code)
        handle.status.last_status = status
        payload_bytes = bytes(cip_resp.payload)
        if status_code not in (0, None):
            raise PLCResponseError(
                "CIP command failed: {}".format(status.message), status=status
            )
        return CommandResult(status=status, payload=payload_bytes)

    def get_status(self, session_id: str) -> ConnectionStatus:
        handle = self._require_session(session_id)
        return handle.status

    def _require_session(self, session_id: str) -> SessionHandle:
        with self._lock:
            handle = self._sessions.get(session_id)
        if handle is None:
            raise PLCManagerError("Unknown session '{}'".format(session_id))
        return handle

    @staticmethod
    def _resolve_sender(client: PLCClient, transport: str):
        mapping = {
            "rr": client.send_rr_cip,
            "rr_cm": client.send_rr_cm_cip,
            "rr_mr": client.send_rr_mr_cip,
            "unit": client.send_unit_cip,
        }
        try:
            return mapping[transport]
        except KeyError:
            raise PLCManagerError("Unsupported transport '{}'".format(transport))

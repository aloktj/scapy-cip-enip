"""High level PLC management utilities.

This module exposes helpers around :class:`plc.PLCClient` to provide
connection pooling, context-managed sessions, and structured responses that can
be consumed by higher level APIs.
"""
from __future__ import annotations

import logging
import socket
import struct
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Deque, Iterator, Optional, Tuple

from scapy.error import Scapy_Exception

from cip import (
    CIP,
    CIP_Path,
    CIP_ReqForwardClose,
    CIP_ReqForwardOpen,
    CIP_ReqReadOtherTag,
    CIP_ResponseStatus,
)
from plc import PLCClient

logger = logging.getLogger(__name__)


class PLCManagerError(Exception):
    """Base class for all PLC management errors."""


class PLCConnectionError(PLCManagerError):
    """Raised when a socket level or session level connection fails."""


class PLCCommunicationError(PLCManagerError):
    """Raised when a low-level Scapy parsing or encoding error occurs."""


class PLCResponseError(PLCManagerError):
    """Raised when a PLC returns an unexpected response."""

    def __init__(self, message: str, status: Optional[CIPStatus] = None):
        super(PLCResponseError, self).__init__(message)
        self.status = status


@dataclass
class CIPStatus:
    """Information about the latest CIP response status."""

    code: Optional[int] = None
    message: Optional[str] = None

    @classmethod
    def from_code(cls, code: Optional[int]) -> "CIPStatus":
        if code is None:
            return cls(None, None)
        message = CIP_ResponseStatus.ERROR_CODES.get(
            code, "Unknown status 0x{:02x}".format(code)
        )
        return cls(code, message)

    @property
    def ok(self) -> bool:
        return self.code in (None, 0)


@dataclass
class ConnectionStatus:
    """Description of the logical connection maintained with a PLC."""

    connected: bool
    session_id: int
    enip_connid: int
    last_status: CIPStatus = field(default_factory=CIPStatus)


@dataclass
class AssemblySnapshot:
    """Structured representation of an assembly read from the PLC."""

    class_id: int
    instance_id: int
    data: bytes
    timestamp: float
    last_status: CIPStatus

    def as_words(self) -> Tuple[int, ...]:
        """Interpret the binary payload as a tuple of 16-bit little-endian words."""
        if len(self.data) % 2:
            raise PLCResponseError("Assembly data size must be even to decode words")
        return struct.unpack("<{}H".format(len(self.data) // 2), self.data)


class PLCConnectionPool:
    """Very small footprint pool for :class:`PLCClient` instances."""

    def __init__(self, plc_addr: str, plc_port: int = 44818, max_size: int = 2):
        self._plc_addr = plc_addr
        self._plc_port = plc_port
        self._max_size = max(1, max_size)
        self._clients: Deque[PLCClient] = deque()
        self._created = 0

    def acquire(self) -> PLCClient:
        try:
            client = self._clients.pop()
            logger.debug("Reusing PLCClient from pool")
        except IndexError:
            if self._created >= self._max_size:
                raise PLCConnectionError("PLC connection pool exhausted")
            client = self._create_client()
            logger.debug("Created new PLCClient for pool")
        return client

    def release(self, client: PLCClient) -> None:
        if len(self._clients) < self._max_size:
            self._clients.append(client)
            logger.debug("PLCClient returned to pool")

    def _create_client(self) -> PLCClient:
        try:
            client = PLCClient(self._plc_addr, self._plc_port)
        except (socket.error, OSError) as exc:
            raise PLCConnectionError("Failed to open PLC socket") from exc
        except Scapy_Exception as exc:
            raise PLCCommunicationError("Failed to build PLC packet") from exc
        self._created += 1
        if not client.connected:
            raise PLCConnectionError("PLCClient failed to establish TCP connection")
        return client


class PLCManager:
    """Context managed access to a PLC with connection pooling."""

    def __init__(self, plc_addr: str, plc_port: int = 44818, pool_size: int = 2):
        self._pool = PLCConnectionPool(plc_addr, plc_port, pool_size)

    @contextmanager
    def session(self, auto_start: bool = True) -> Iterator[Tuple[PLCClient, ConnectionStatus]]:
        client = self._pool.acquire()
        status = ConnectionStatus(
            connected=client.connected,
            session_id=getattr(client, "session_id", 0),
            enip_connid=getattr(client, "enip_connid", 0),
            last_status=CIPStatus(),
        )
        if not client.connected:
            self._pool.release(client)
            raise PLCConnectionError("PLCClient is not connected")

        try:
            if auto_start:
                status = self.start_session(client)
            yield client, status
        except (socket.error, OSError) as exc:
            raise PLCConnectionError("Socket failure during PLC communication") from exc
        except Scapy_Exception as exc:
            raise PLCCommunicationError("Scapy failure during PLC communication") from exc
        finally:
            try:
                if auto_start and client.connected:
                    self.stop_session(client)
            finally:
                self._pool.release(client)

    def start_session(self, client: PLCClient) -> ConnectionStatus:
        status = self._forward_open(client)
        return ConnectionStatus(
            connected=client.connected,
            session_id=getattr(client, "session_id", 0),
            enip_connid=getattr(client, "enip_connid", 0),
            last_status=status,
        )

    def stop_session(self, client: PLCClient) -> CIPStatus:
        return self._forward_close(client)

    def fetch_assembly(
        self,
        class_id: int,
        instance_id: int,
        total_size: int,
        auto_start: bool = True,
    ) -> AssemblySnapshot:
        """Read the full content of an assembly from the PLC."""
        with self.session(auto_start=auto_start) as (client, status):
            data, last_status = self._read_full_tag(client, class_id, instance_id, total_size)
            return AssemblySnapshot(
                class_id=class_id,
                instance_id=instance_id,
                data=data,
                timestamp=time.time(),
                last_status=last_status,
            )

    def _forward_open(self, client: PLCClient) -> CIPStatus:
        cippkt = CIP(service=0x54, path=CIP_Path(wordsize=2, path=b"\x20\x06\x24\x01"))
        cippkt /= CIP_ReqForwardOpen(path_wordsize=3, path=b"\x01\x00\x20\x02\x24\x01")
        client.send_rr_cip(cippkt)
        response = client.recv_enippkt()
        if response is None:
            raise PLCResponseError("No response received for Forward Open request")
        cip_resp = response[CIP]
        status_code = int(cip_resp.status[0].status)
        status = CIPStatus.from_code(status_code)
        if status_code != 0:
            raise PLCResponseError(
                "Failed to Forward Open CIP connection: {}".format(status.message),
                status=status,
            )
        if not hasattr(cip_resp.payload, "OT_network_connection_id"):
            raise PLCResponseError(
                "Forward Open response missing connection identifier", status=status
            )
        client.enip_connid = cip_resp.payload.OT_network_connection_id
        return status

    def _forward_close(self, client: PLCClient) -> CIPStatus:
        cippkt = CIP(service=0x4E, path=CIP_Path(wordsize=2, path=b"\x20\x06\x24\x01"))
        cippkt /= CIP_ReqForwardClose(path_wordsize=3, path=b"\x01\x00\x20\x02\x24\x01")
        client.send_rr_cip(cippkt)
        response = client.recv_enippkt()
        if response is None:
            raise PLCResponseError("No response received for Forward Close request")
        cip_resp = response[CIP]
        status_code = int(cip_resp.status[0].status)
        status = CIPStatus.from_code(status_code)
        if status_code != 0:
            raise PLCResponseError(
                "Failed to Forward Close CIP connection: {}".format(status.message),
                status=status,
            )
        return status

    def _read_full_tag(
        self,
        client: PLCClient,
        class_id: int,
        instance_id: int,
        total_size: int,
    ) -> Tuple[bytes, CIPStatus]:
        data_chunks = []
        offset = 0
        remaining_size = total_size
        last_status = CIPStatus()

        while remaining_size > 0:
            cippkt = CIP(
                service=0x4C,
                path=CIP_Path.make(class_id=class_id, instance_id=instance_id),
            )
            cippkt /= CIP_ReqReadOtherTag(start=offset, length=remaining_size)
            client.send_rr_cm_cip(cippkt)
            response = client.recv_enippkt()
            if response is None:
                raise PLCResponseError("No response received while reading tag")

            cip_resp = response[CIP]
            status_code = int(cip_resp.status[0].status)
            last_status = CIPStatus.from_code(status_code)
            payload = bytes(cip_resp.payload)

            if status_code == 0:
                if len(payload) != remaining_size:
                    raise PLCResponseError(
                        "Unexpected payload size. Expected {}, got {}".format(
                            remaining_size, len(payload)
                        ),
                        status=last_status,
                    )
            elif status_code == 6 and len(payload) > 0:
                # Partial response. Continue requesting the remaining bytes.
                pass
            else:
                raise PLCResponseError(
                    "Error reading tag: {}".format(last_status.message),
                    status=last_status,
                )

            data_chunks.append(payload)
            offset += len(payload)
            remaining_size -= len(payload)

        return b"".join(data_chunks), last_status


__all__ = [
    "AssemblySnapshot",
    "CIPStatus",
    "ConnectionStatus",
    "PLCCommunicationError",
    "PLCConnectionError",
    "PLCManager",
    "PLCManagerError",
    "PLCResponseError",
]

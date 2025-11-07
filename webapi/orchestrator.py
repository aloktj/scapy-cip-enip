"""Session orchestration helpers bridging the PLC manager and web API."""
from __future__ import annotations

import binascii
import logging
import struct
import threading
import time
import uuid
from dataclasses import dataclass, field
from queue import Empty
from typing import Dict, Iterable, List, Literal, Optional

from scapy import all as scapy_all

from cip import CIP, CIP_Path
from enip_udp import ENIP_UDP_KEEPALIVE
from services.io_runtime import (
    AssemblyDirectionError,
    AssemblyNotRegisteredError,
    AssemblyRuntimeError,
    AssemblyRuntimeView,
    IORuntime,
)
from services.plc_manager import (
    AssemblySnapshot,
    CIPStatus,
    ConnectionStatus,
    PLCConnectionError,
    PLCManager,
    PLCManagerError,
    PLCResponseError,
)
from plc import PLCClient

logger = logging.getLogger(__name__)

__all__ = ["CommandResult", "SessionDiagnostics", "SessionHandle", "SessionOrchestrator"]


@dataclass
class SessionHandle:
    """Representation of a PLC session managed by the orchestrator."""

    session_id: str
    client: PLCClient
    status: ConnectionStatus
    host: str
    port: int
    created_at: float = field(default_factory=time.time)
    last_activity_at: float = field(default_factory=time.time)
    io_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


@dataclass
class _SessionLoopState:
    stop_event: threading.Event
    threads: List[threading.Thread] = field(default_factory=list)


@dataclass
class SessionDiagnostics:
    """Snapshot of diagnostic information derived from a PLC session."""

    session_id: str
    connection: ConnectionStatus
    host: str
    port: int
    keep_alive_pattern_hex: str
    keep_alive_active: bool
    last_activity_at: float


@dataclass
class CommandResult:
    """Result of a low level CIP command execution."""

    status: CIPStatus
    payload: bytes = b""


class SessionOrchestrator:
    """Coordinate PLC sessions that are shared across API requests."""

    KEEPALIVE_IDLE_SECONDS = 10.0

    def __init__(
        self,
        manager: PLCManager,
        *,
        io_runtime: Optional[IORuntime] = None,
        poll_interval: float = 0.5,
        output_timeout: float = 2.0,
    ):
        self._manager = manager
        self._sessions: Dict[str, SessionHandle] = {}
        self._lock = threading.Lock()
        self._runtime = io_runtime or IORuntime()
        self._session_loops: Dict[str, _SessionLoopState] = {}
        self._poll_interval = max(0.05, float(poll_interval))
        self._output_timeout = max(0.1, float(output_timeout))

    def start_session(
        self, *, host: Optional[str] = None, port: Optional[int] = None
    ) -> SessionHandle:
        """Start a new PLC session and keep it active until explicitly stopped."""
        resolved_host, resolved_port = self._manager.resolve_endpoint(host, port)
        client = self._manager.acquire_client(host=resolved_host, port=resolved_port)
        try:
            status = self._manager.start_session(client)
        except Exception:
            self._manager.release_client(client)
            raise

        session_id = uuid.uuid4().hex
        handle = SessionHandle(
            session_id=session_id,
            client=client,
            status=status,
            host=resolved_host,
            port=resolved_port,
        )
        handle.status.host = resolved_host
        handle.status.port = resolved_port
        self._refresh_status(handle)
        self._mark_activity(handle)
        with self._lock:
            self._sessions[session_id] = handle
        self._start_io_loops(handle)
        return handle

    def stop_session(self, session_id: str) -> ConnectionStatus:
        handle = self._require_session(session_id)
        self._stop_io_loops(session_id)
        try:
            status = self._manager.stop_session(handle.client)
            self._refresh_status(handle)
        finally:
            self._manager.release_client(handle.client)
            with self._lock:
                self._sessions.pop(session_id, None)
        handle.status.last_status = status
        handle.status.connected = False
        self._mark_activity(handle)
        return handle.status

    def read_assembly(self, session_id: str, class_id: int, instance_id: int, total_size: int) -> AssemblySnapshot:
        handle = self._require_session(session_id)
        with handle.io_lock:
            data, status = self._manager._read_full_tag(
                handle.client, class_id, instance_id, total_size
            )
        handle.status.last_status = status
        self._refresh_status(handle)
        self._mark_activity(handle)
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
        with handle.io_lock:
            handle.client.send_rr_cm_cip(cippkt)
            try:
                response = handle.client.recv_enippkt()
            except PLCConnectionError as exc:
                raise PLCConnectionError(
                    "Socket closed while waiting for attribute write response"
                ) from exc
        if response is None:
            raise PLCResponseError("No response received for attribute write")
        cip_resp = response[CIP]
        status_code = int(cip_resp.status[0].status)
        status = CIPStatus.from_code(status_code)
        handle.status.last_status = status
        self._refresh_status(handle)
        self._mark_activity(handle)
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
        with handle.io_lock:
            sender(cippkt)
            try:
                response = handle.client.recv_enippkt()
            except PLCConnectionError as exc:
                raise PLCConnectionError("Socket closed while waiting for command response") from exc
        if response is None:
            raise PLCResponseError("No response received for command")
        cip_resp = response[CIP]
        status_code = int(cip_resp.status[0].status)
        status = CIPStatus.from_code(status_code)
        handle.status.last_status = status
        payload_bytes = bytes(cip_resp.payload)
        self._refresh_status(handle)
        self._mark_activity(handle)
        if status_code not in (0, None):
            raise PLCResponseError(
                "CIP command failed: {}".format(status.message), status=status
            )
        return CommandResult(status=status, payload=payload_bytes)

    def get_status(self, session_id: str) -> ConnectionStatus:
        handle = self._require_session(session_id)
        self._refresh_status(handle)
        return handle.status

    # ------------------------------------------------------------------
    # Assembly runtime helpers
    # ------------------------------------------------------------------
    def apply_configuration(self, configuration) -> None:
        """Register assemblies declared in *configuration* and refresh loops."""

        self._runtime.load(configuration)
        with self._lock:
            handles = list(self._sessions.values())
        for handle in handles:
            self._stop_io_loops(handle.session_id)
            self._start_io_loops(handle)

    def get_assembly_state(self, session_id: str, alias: str) -> AssemblyRuntimeView:
        handle = self._require_session(session_id)
        try:
            view = self._runtime.get_view(alias)
        except AssemblyNotRegisteredError:
            raise
        if view.timestamp is None and self._runtime.configured:
            try:
                with handle.io_lock:
                    data, status = self._runtime.fetch(self._manager, handle.client, alias)
                handle.status.last_status = status
                self._mark_activity(handle)
                view = self._runtime.get_view(alias)
            except AssemblyRuntimeError:
                raise
        return view

    def write_assembly(self, session_id: str, alias: str, payload: bytes) -> CIPStatus:
        handle = self._require_session(session_id)
        request = self._runtime.queue_output(alias, payload)
        self._mark_activity(handle)
        try:
            status = request.wait(timeout=self._output_timeout)
        except TimeoutError as exc:
            raise PLCManagerError(str(exc)) from exc
        handle.status.last_status = status
        self._mark_activity(handle)
        return status

    def get_diagnostics(self, session_id: str) -> SessionDiagnostics:
        handle = self._require_session(session_id)
        self._refresh_status(handle)
        keep_alive_pattern_hex = binascii.hexlify(ENIP_UDP_KEEPALIVE).decode("ascii")
        keep_alive_active = (time.time() - handle.last_activity_at) <= self.KEEPALIVE_IDLE_SECONDS
        return SessionDiagnostics(
            session_id=session_id,
            connection=handle.status,
            host=handle.host,
            port=handle.port,
            keep_alive_pattern_hex=keep_alive_pattern_hex,
            keep_alive_active=keep_alive_active,
            last_activity_at=handle.last_activity_at,
        )

    def _refresh_status(self, handle: SessionHandle) -> None:
        handle.status.connected = handle.client.connected
        handle.status.session_id = getattr(handle.client, "session_id", handle.status.session_id)
        handle.status.enip_connid = getattr(handle.client, "enip_connid", handle.status.enip_connid)
        handle.status.sequence = getattr(handle.client, "sequence", handle.status.sequence)

    def _mark_activity(self, handle: SessionHandle) -> None:
        handle.last_activity_at = time.time()

    def _require_session(self, session_id: str) -> SessionHandle:
        with self._lock:
            handle = self._sessions.get(session_id)
        if handle is None:
            raise PLCManagerError("Unknown session '{}'".format(session_id))
        return handle

    def _start_io_loops(self, handle: SessionHandle) -> None:
        if not self._runtime.configured:
            return
        stop_event = threading.Event()
        threads: List[threading.Thread] = []
        for alias in self._runtime.input_assemblies():
            thread = threading.Thread(
                target=self._input_poll_loop,
                args=(handle.session_id, alias, stop_event),
                daemon=True,
            )
            thread.start()
            threads.append(thread)
        for alias in self._runtime.output_assemblies():
            thread = threading.Thread(
                target=self._output_dispatch_loop,
                args=(handle.session_id, alias, stop_event),
                daemon=True,
            )
            thread.start()
            threads.append(thread)
        if threads:
            self._session_loops[handle.session_id] = _SessionLoopState(
                stop_event=stop_event, threads=threads
            )

    def _stop_io_loops(self, session_id: str) -> None:
        state = self._session_loops.pop(session_id, None)
        if state is None:
            return
        state.stop_event.set()
        for thread in state.threads:
            thread.join(timeout=0.2)

    def _input_poll_loop(self, session_id: str, alias: str, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            try:
                handle = self._require_session(session_id)
            except PLCManagerError:
                return
            try:
                with handle.io_lock:
                    data, status = self._runtime.fetch(self._manager, handle.client, alias)
                handle.status.last_status = status
                self._mark_activity(handle)
            except AssemblyRuntimeError as exc:
                logger.debug("Assembly poll failed for %s: %s", alias, exc)
            except PLCResponseError as exc:
                logger.debug("CIP error while polling %s: %s", alias, exc)
            except Exception as exc:  # pragma: no cover - defensive guard
                logger.exception("Unexpected error polling assembly %s", alias, exc_info=exc)
            finally:
                stop_event.wait(self._poll_interval)

    def _output_dispatch_loop(
        self, session_id: str, alias: str, stop_event: threading.Event
    ) -> None:
        while not stop_event.is_set():
            try:
                request = self._runtime.await_output(alias, timeout=0.1)
            except AssemblyDirectionError:
                return
            except Empty:
                continue
            try:
                handle = self._require_session(session_id)
            except PLCManagerError:
                request.complete(CIPStatus(), error=PLCManagerError("Session closed"))
                continue
            try:
                with handle.io_lock:
                    status = self._runtime.send_output(handle.client, alias, request.payload)
                handle.status.last_status = status
                self._mark_activity(handle)
                request.complete(status)
            except PLCResponseError as exc:
                if exc.status is not None:
                    handle.status.last_status = exc.status
                request.complete(exc.status or CIPStatus(), error=exc)
                logger.debug("Failed to write assembly %s: %s", alias, exc)
            except AssemblyRuntimeError as exc:
                request.complete(CIPStatus(), error=exc)
                logger.debug("Assembly runtime error during write for %s: %s", alias, exc)
            except Exception as exc:  # pragma: no cover - defensive guard
                logger.exception("Unexpected error writing assembly %s", alias, exc_info=exc)
                request.complete(CIPStatus(), error=exc)

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

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Tuple

import sys

sys.path.append(str(Path(__file__).resolve().parent.parent))

import pytest
from scapy import all as scapy_all

from cip import CIP, CIP_Path, CIP_ResponseStatus
from enip_tcp import ENIP_TCP
from services.plc_manager import CIPStatus, ConnectionStatus


class DummyClient:
    """Stand-in PLC client used to isolate orchestrator tests."""

    def __init__(self) -> None:
        self.connected = True
        self.session_id = 0x100
        self.enip_connid = 0x200
        self.sequence = 1
        self.sent: List[Tuple[str, object]] = []
        self._responses: List[object] = []

    def queue_response(self, packet) -> None:
        self._responses.append(packet)

    def recv_enippkt(self):
        if self._responses:
            return self._responses.pop(0)
        return None

    def send_rr_cip(self, packet) -> None:
        self.sent.append(("rr", packet))

    def send_rr_cm_cip(self, packet) -> None:
        self.sent.append(("rr_cm", packet))

    def send_rr_mr_cip(self, packet) -> None:
        self.sent.append(("rr_mr", packet))

    def send_unit_cip(self, packet) -> None:
        self.sent.append(("unit", packet))
        self.sequence += 1


@dataclass
class DummyPool:
    client: DummyClient
    released: List[DummyClient]

    def __init__(self, client: DummyClient) -> None:
        self.client = client
        self.released = []

    def acquire(self) -> DummyClient:
        return self.client

    def release(self, client: DummyClient) -> None:
        self.released.append(client)


class DummyManager:
    """Utility PLC manager with deterministic behaviour for tests."""

    def __init__(self, client: DummyClient, read_payload: bytes = b"\x01\x02") -> None:
        self._pool = DummyPool(client)
        self._read_payload = read_payload
        self.start_calls = 0

    def start_session(self, client: DummyClient) -> ConnectionStatus:
        self.start_calls += 1
        status = CIPStatus.from_code(0)
        return ConnectionStatus(
            connected=client.connected,
            session_id=client.session_id,
            enip_connid=client.enip_connid,
            sequence=self.start_calls,
            last_status=status,
        )

    def stop_session(self, client: DummyClient) -> CIPStatus:
        return CIPStatus.from_code(0)

    def _read_full_tag(
        self, client: DummyClient, class_id: int, instance_id: int, total_size: int
    ) -> Tuple[bytes, CIPStatus]:
        return self._read_payload[:total_size], CIPStatus.from_code(0)


@pytest.fixture()
def dummy_client() -> DummyClient:
    return DummyClient()


@pytest.fixture()
def build_manager() -> Callable[[DummyClient, bytes], DummyManager]:
    def factory(client: DummyClient, read_payload: bytes = b"\x01\x02") -> DummyManager:
        return DummyManager(client, read_payload=read_payload)

    return factory


@pytest.fixture()
def make_cip_response():
    def factory(status: int = 0, payload: bytes = b"", service: int = 0x4C):
        packet = ENIP_TCP(command_id=0x006F, session=1)
        cip_layer = CIP(
            direction=1, service=service, status=[CIP_ResponseStatus(status=status)]
        )
        if payload:
            cip_layer /= scapy_all.Raw(load=payload)
        packet /= cip_layer
        return packet

    return factory


@pytest.fixture()
def example_path() -> CIP_Path:
    return CIP_Path.make(class_id=0x04, instance_id=0x64)

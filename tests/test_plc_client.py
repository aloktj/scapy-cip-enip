from __future__ import annotations

import pytest
from scapy import all as scapy_all

from cip import CIP, CIP_Path
from enip_tcp import ENIP_SendRRData, ENIP_SendUnitData_Item, ENIP_TCP
from errors import PLCConnectionError
from plc import PLCClient


class _ChunkedSocket:
    """Socket-like object returning data in predefined chunks."""

    def __init__(self, data: bytes, chunk_sizes: list[int]) -> None:
        self._buffer = bytearray(data)
        self._chunk_sizes = list(chunk_sizes)

    def recv(self, size: int) -> bytes:
        if not self._buffer:
            return b""
        requested = size
        chunk_size = self._chunk_sizes.pop(0) if self._chunk_sizes else requested
        chunk_size = max(0, min(chunk_size, requested, len(self._buffer)))
        if chunk_size == 0:
            return b""
        data = bytes(self._buffer[:chunk_size])
        del self._buffer[:chunk_size]
        return data


def _make_enip_packet(payload: bytes) -> bytes:
    cip_layer = CIP(path=CIP_Path.make(class_id=1, instance_id=1))
    if payload:
        cip_layer /= scapy_all.Raw(load=payload)
    packet = ENIP_TCP(session=0x1234)
    packet /= ENIP_SendRRData(
        items=[
            ENIP_SendUnitData_Item(type_id=0x0000),
            ENIP_SendUnitData_Item(type_id=0x00b2) / cip_layer,
        ]
    )
    return bytes(packet)


def test_recv_enippkt_reassembles_partial_reads() -> None:
    payload = b"\x11\x22\x33\x44"
    raw_packet = _make_enip_packet(payload)
    header_chunks = [8, 4, 12]  # Split the 24-byte header
    payload_chunks = [1, 2, len(raw_packet) - 24 - 3]
    sock = _ChunkedSocket(raw_packet, header_chunks + payload_chunks)

    client = PLCClient.__new__(PLCClient)
    client.sock = sock
    client._offline = False

    packet = client.recv_enippkt()
    assert bytes(packet) == raw_packet


def test_recv_enippkt_raises_on_premature_eof() -> None:
    payload = b"\x99\x88\x77\x66"
    raw_packet = _make_enip_packet(payload)
    truncated = raw_packet[:24]  # drop the payload completely
    sock = _ChunkedSocket(truncated, [16, 8])

    client = PLCClient.__new__(PLCClient)
    client.sock = sock
    client._offline = False

    with pytest.raises(PLCConnectionError):
        client.recv_enippkt()

"""Tests covering Forward Open request encoding nuances."""

from cip import CIP, CIP_Path, CIP_ReqForwardOpen, CIP_ConnectionParam


def build_forward_open(**kwargs) -> bytes:
    request = CIP(service=0x54, path=CIP_Path(wordsize=2, path=b"\x20\x06\x24\x01"))
    request /= CIP_ReqForwardOpen(**kwargs)
    return bytes(request)


def test_forward_open_includes_connection_parameters() -> None:
    raw = build_forward_open(path_wordsize=3, path=b"\x01\x00\x20\x02\x24\x01")
    # Default connection parameter values occupy two bytes each and must be
    # present in the payload.  Scapy previously emitted zero-length fields which
    # produced malformed packets on the wire.
    assert b"\xf4\x41" in raw


def test_forward_open_respects_custom_connection_sizes() -> None:
    raw = build_forward_open(
        OT_connection_param=CIP_ConnectionParam(connection_size=140),
        TO_connection_param=CIP_ConnectionParam(connection_size=142),
        path_wordsize=3,
        path=b"\x01\x00\x20\x02\x24\x01",
    )
    # Little-endian encoding of the requested connection sizes.
    assert b"\x8c\x40" in raw
    assert b"\x8e\x40" in raw

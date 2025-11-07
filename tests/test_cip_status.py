from cip import CIP


def test_cip_response_defaults_to_success_status_when_missing():
    # Response service bit set (0x80) but without explicit general status bytes.
    raw = b"\xD4"  # Forward Open response with no payload or status
    pkt = CIP(raw)

    assert len(pkt.status) == 1
    status = pkt.status[0]
    assert status.status == 0
    assert status.additional_size == 0

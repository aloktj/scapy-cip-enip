from __future__ import annotations

import binascii
import time

import pytest

from cip import CIP_Path
from enip_udp import ENIP_UDP_KEEPALIVE
from services.config_loader import (
    AssemblyDefinition,
    AssemblyMember,
    DeviceConfiguration,
    DeviceIdentity,
)
from services.io_runtime import IORuntime, AssemblyDirectionError
from services.plc_manager import PLCResponseError
from webapi.orchestrator import SessionOrchestrator


def test_send_command_success(dummy_client, build_manager, make_cip_response, example_path):
    dummy_client.queue_response(make_cip_response(status=0, payload=b"\xAA\xBB"))
    orchestrator = SessionOrchestrator(build_manager(dummy_client))
    handle = orchestrator.start_session()

    result = orchestrator.send_command(
        handle.session_id, service=0x4C, path=example_path, payload=b""
    )

    assert result.status.code == 0
    assert result.payload == b"\xAA\xBB"
    assert dummy_client.sent[-1][0] == "rr_cm"


def test_send_command_failure(dummy_client, build_manager, make_cip_response, example_path):
    dummy_client.queue_response(make_cip_response(status=0x0E))
    orchestrator = SessionOrchestrator(build_manager(dummy_client))
    handle = orchestrator.start_session()

    with pytest.raises(PLCResponseError):
        orchestrator.send_command(
            handle.session_id, service=0x4C, path=example_path, payload=b""
        )


def test_read_assembly_and_stop_session(dummy_client, build_manager):
    payload = b"\x01\x02\x03\x04"
    orchestrator = SessionOrchestrator(build_manager(dummy_client, read_payload=payload))
    handle = orchestrator.start_session()

    snapshot = orchestrator.read_assembly(handle.session_id, 0x04, 0x64, len(payload))

    assert snapshot.data == payload
    assert snapshot.last_status.code == 0

    connection = orchestrator.stop_session(handle.session_id)
    assert connection.last_status.code == 0
    assert not handle.status.connected


def test_session_diagnostics(dummy_client, build_manager):
    orchestrator = SessionOrchestrator(build_manager(dummy_client))
    handle = orchestrator.start_session()

    diagnostics = orchestrator.get_diagnostics(handle.session_id)
    expected_hex = binascii.hexlify(ENIP_UDP_KEEPALIVE).decode("ascii")

    assert diagnostics.session_id == handle.session_id
    assert diagnostics.keep_alive_pattern_hex == expected_hex
    assert diagnostics.keep_alive_active is True
    assert diagnostics.connection.last_status.code == 0
    assert diagnostics.host == handle.host
    assert diagnostics.port == handle.port

    # Ensure activity timestamp updates after operations
    before = diagnostics.last_activity_at
    time.sleep(0.01)
    orchestrator.get_status(handle.session_id)
    after = orchestrator.get_diagnostics(handle.session_id).last_activity_at
    assert after >= before


def test_start_session_with_custom_endpoint(dummy_client, build_manager):
    orchestrator = SessionOrchestrator(build_manager(dummy_client))

    handle = orchestrator.start_session(host="192.0.2.10", port=502)

    assert handle.host == "192.0.2.10"
    assert handle.port == 502

    connection = orchestrator.stop_session(handle.session_id)
    assert connection.host == "192.0.2.10"
    assert connection.port == 502


def _build_runtime_configuration() -> DeviceConfiguration:
    return DeviceConfiguration(
        identity=DeviceIdentity(name="Runtime Test"),
        assemblies=(
            AssemblyDefinition(
                alias="Inputs",
                class_id=0x04,
                instance_id=0x64,
                direction="input",
                size=4,
                members=(
                    AssemblyMember(name="Word0", offset=0, size=2, datatype="uint16"),
                    AssemblyMember(name="Word1", offset=2, size=2, datatype="uint16"),
                ),
            ),
            AssemblyDefinition(
                alias="Outputs",
                class_id=0x04,
                instance_id=0x65,
                direction="output",
                size=4,
                members=(),
            ),
        ),
    )


def test_get_assembly_state_triggers_fetch(dummy_client, build_manager):
    runtime = IORuntime()
    runtime.load(_build_runtime_configuration())
    orchestrator = SessionOrchestrator(
        build_manager(dummy_client, read_payload=b"\x01\x02\x03\x04"),
        io_runtime=runtime,
        poll_interval=0.05,
    )
    handle = orchestrator.start_session()

    view = orchestrator.get_assembly_state(handle.session_id, "inputs")

    assert view.payload == b"\x01\x02\x03\x04"
    assert view.status.code == 0
    assert view.word_values == (0x0201, 0x0403)


def test_write_assembly_enforces_direction(dummy_client, build_manager, make_cip_response):
    runtime = IORuntime()
    runtime.load(_build_runtime_configuration())
    orchestrator = SessionOrchestrator(
        build_manager(dummy_client), io_runtime=runtime, poll_interval=0.05
    )
    handle = orchestrator.start_session()

    dummy_client.queue_response(make_cip_response(status=0))
    status = orchestrator.write_assembly(handle.session_id, "outputs", b"\x00\x01\x02\x03")

    assert status.code == 0
    assert dummy_client.sent[-1][0] == "unit"

    with pytest.raises(AssemblyDirectionError):
        orchestrator.write_assembly(handle.session_id, "inputs", b"\x00\x00\x00\x00")

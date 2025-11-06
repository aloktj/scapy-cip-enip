from __future__ import annotations

import pytest

from cip import CIP_Path
from services.assembly_config import (
    AssemblyConfigService,
    AssemblyPathRegistry,
    AssemblyUpdateError,
    install_default_offline_fixtures,
)


class FakePLCClient:
    def __init__(self, attributes, status_queue=None):
        self.attributes = {key: dict(value) for key, value in attributes.items()}
        self.status_queue = list(status_queue or [])

    def get_attribute(self, class_id, instance_id, attribute_id):
        return self.attributes[(class_id, instance_id)][attribute_id]

    def set_attribute(self, class_id, instance_id, attribute_id, value):
        if self.status_queue:
            return self.status_queue.pop(0)
        self.attributes[(class_id, instance_id)][attribute_id] = value
        return 0


@pytest.fixture()
def assembly_client():
    install_default_offline_fixtures(overwrite=True)
    base = {
        (0x04, 0x64): {
            0x03: (16).to_bytes(2, "little"),
            0x04: (0).to_bytes(2, "little"),
            0x09: (10).to_bytes(2, "little"),
            0x0B: (1).to_bytes(1, "little"),
        }
    }
    return FakePLCClient(base)


def test_read_attribute_set(assembly_client):
    service = AssemblyConfigService(assembly_client)
    values = service.read_attribute_set((0x04, 0x64), "io_sizes")
    assert values == {"input_size": 16, "output_size": 0}


def test_update_attributes_rolls_back_on_partial(assembly_client):
    failure_client = FakePLCClient(
        assembly_client.attributes,
        status_queue=[0, 0x06],
    )
    service = AssemblyConfigService(failure_client)

    with pytest.raises(AssemblyUpdateError):
        service.update_attributes((0x04, 0x64), {"input_size": 32, "output_size": 8})

    restored = service.read_attribute_set((0x04, 0x64), "io_sizes")
    assert restored == {"input_size": 16, "output_size": 0}


def test_registry_alias_resolution():
    registry = AssemblyPathRegistry({"inputs": (0x04, 0x64)})
    class_id, instance_id = registry.resolve("inputs")
    assert (class_id, instance_id) == (0x04, 0x64)
    path = registry.path_for("inputs", attribute_id=0x03)
    expected = CIP_Path.make(class_id=0x04, instance_id=0x64, attribute_id=0x03)
    assert path.path == expected.path

from __future__ import annotations

from pathlib import Path

import pytest

from services.config_loader import ConfigurationValidationError, load_configuration


CIP_WITH_MEMBER_IDS = """
<cip>
  <identity name="Sample PLC" />
  <assemblies>
    <assembly name="InAssembly" dir="in" instanceId="0x64">
      <members>
        <member>
          <usint id="MPU_CTCMSAlive" offset="0" />
        </member>
        <member name="Explicit">
          <uint id="ExplicitID" offset="1" />
        </member>
      </members>
    </assembly>
    <assembly alias="OutAssembly" dir="out" instanceId="0x65">
      <bool id="StatusFlag" offset="0" />
    </assembly>
  </assemblies>
</cip>
""".strip()


ASSEMBLY_TEMPLATE_ATTRIBUTES = """
<cip>
  <assemblies>
    <assembly name="Inputs" connectionPoint="0x64" dir="t2o" sizeBytes="16">
      <members>
        <member>
          <uint name="Word" />
        </member>
      </members>
    </assembly>
    <assembly alias="Outputs" id="0x65" dir="o2t" byteLength="4">
      <bool name="Flag" />
    </assembly>
    <assembly name="Settings" instance="0x66" dir="config">
      <members />
    </assembly>
  </assemblies>
</cip>
""".strip()


IDENTITY_WITH_MAJOR_MINOR_REV = """
<cip>
  <identity majorRev="1" minorRev="2" />
</cip>
""".strip()


def test_load_configuration_supports_member_id_names():
    configuration = load_configuration(CIP_WITH_MEMBER_IDS)
    assemblies = {assembly.alias: assembly for assembly in configuration.assemblies}

    input_members = assemblies["InAssembly"].members
    assert [member.name for member in input_members] == [
        "MPU_CTCMSAlive",
        "Explicit",
    ]

    output_members = assemblies["OutAssembly"].members
    assert [member.name for member in output_members] == ["StatusFlag"]


def test_load_configuration_accepts_generic_adapter_template():
    sample_path = Path("docs/samples/generic_adapter_template.xml")
    payload = sample_path.read_text(encoding="utf-8")

    try:
        load_configuration(payload)
    except ConfigurationValidationError as exc:
        pytest.fail(f"Unexpected validation error: {exc}")


def test_identity_revision_prefers_major_minor_attributes():
    configuration = load_configuration(IDENTITY_WITH_MAJOR_MINOR_REV)
    assert configuration.identity.revision == "1.2"


def test_parse_template_style_assembly_attributes():
    configuration = load_configuration(ASSEMBLY_TEMPLATE_ATTRIBUTES)
    assemblies = {assembly.alias: assembly for assembly in configuration.assemblies}

    inputs = assemblies["Inputs"]
    assert inputs.instance_id == 0x64
    assert inputs.direction == "input"
    assert inputs.size == 16

    outputs = assemblies["Outputs"]
    assert outputs.instance_id == 0x65
    assert outputs.direction == "output"
    assert outputs.size == 4

    settings = assemblies["Settings"]
    assert settings.instance_id == 0x66
    assert settings.direction == "configuration"

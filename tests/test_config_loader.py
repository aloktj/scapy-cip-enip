from __future__ import annotations

from pathlib import Path

from services.config_loader import load_configuration


CIP_WITH_MEMBER_IDS = """
<cip>
  <identity name="Sample PLC" />
  <assemblies>
    <assembly id="InAssembly" dir="in" instanceId="0x64">
      <members>
        <member>
          <usint id="MPU_CTCMSAlive" offset="0" />
        </member>
        <member name="Explicit">
          <uint id="ExplicitID" offset="1" />
        </member>
      </members>
    </assembly>
    <assembly id="OutAssembly" dir="out" instanceId="0x65">
      <bool id="StatusFlag" offset="0" />
    </assembly>
  </assemblies>
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

    load_configuration(payload)


def test_identity_revision_from_major_minor_aliases():
    payload = """
    <Device>
      <Identity majorRev="4" minorRev="2" />
    </Device>
    """.strip()

    configuration = load_configuration(payload)

    assert configuration.identity.revision == "4.2"

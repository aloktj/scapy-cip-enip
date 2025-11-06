from __future__ import annotations

from fastapi.testclient import TestClient

from webapi import create_app

AUTH_TOKEN = "super-secret"


def _auth_headers():
    return {"Authorization": f"Bearer {AUTH_TOKEN}"}


CONFIG_XML = """
<DeviceConfiguration>
  <Identity name="Test PLC" vendor="ACME" product="42" revision="1.2.3" />
  <Assemblies>
    <Assembly alias="inputs" class_id="0x04" instance_id="0x64" direction="input" size="16">
      <Member name="Word0" datatype="uint16" offset="0" size="2" description="First word" />
    </Assembly>
    <Assembly alias="outputs" class_id="0x04" instance_id="0x65" direction="output" size="8" />
  </Assemblies>
</DeviceConfiguration>
""".strip()


def test_routes_require_authentication(build_manager, dummy_client):
    app = create_app(build_manager(dummy_client), auth_token=AUTH_TOKEN)
    client = TestClient(app)

    response = client.post("/sessions")
    assert response.status_code == 401

    response = client.post("/sessions", headers=_auth_headers())
    assert response.status_code == 201


def test_session_lifecycle_and_commands(build_manager, dummy_client, make_cip_response):
    app = create_app(build_manager(dummy_client), auth_token=AUTH_TOKEN)
    client = TestClient(app)

    start = client.post("/sessions", headers=_auth_headers())
    assert start.status_code == 201
    session_id = start.json()["session_id"]

    status = client.get(f"/sessions/{session_id}", headers=_auth_headers())
    assert status.status_code == 200
    assert status.json()["connection"]["connected"] is True

    read = client.get(
        f"/sessions/{session_id}/assemblies",
        headers=_auth_headers(),
        params={"class_id": 0x04, "instance_id": 0x64, "total_size": 4},
    )
    assert read.status_code == 200
    assert read.json()["status"]["code"] == 0

    dummy_client.queue_response(make_cip_response(status=0))
    update = client.patch(
        f"/sessions/{session_id}/assemblies/ignored",
        headers=_auth_headers(),
        json={
            "attribute_id": 0x03,
            "value_hex": "0001",
            "path": {"class_id": 0x04, "instance_id": 0x64},
        },
    )
    assert update.status_code == 200
    assert update.json()["code"] == 0

    dummy_client.queue_response(make_cip_response(status=0, payload=b"\x10\x20"))
    command = client.post(
        f"/sessions/{session_id}/commands",
        headers=_auth_headers(),
        json={
            "service": 0x4C,
            "path": {"class_id": 0x04, "instance_id": 0x64},
            "payload_hex": None,
            "transport": "rr_cm",
        },
    )
    assert command.status_code == 200
    assert command.json()["status"]["code"] == 0
    assert command.json()["payload_hex"] == "1020"

    stop = client.delete(f"/sessions/{session_id}", headers=_auth_headers())
    assert stop.status_code == 200
    assert stop.json()["connection"]["connected"] is False


def test_configuration_upload_and_listing(build_manager, dummy_client):
    app = create_app(build_manager(dummy_client), auth_token=AUTH_TOKEN)
    client = TestClient(app)

    upload = client.post(
        "/config",
        headers=_auth_headers(),
        json={"xml": CONFIG_XML},
    )
    assert upload.status_code == 201
    payload = upload.json()
    assert payload["loaded"] is True
    assert payload["identity"]["name"] == "Test PLC"
    assert len(payload["assemblies"]) == 2

    listing = client.get("/config", headers=_auth_headers())
    assert listing.status_code == 200
    assert listing.json()["loaded"] is True
    assert listing.json()["assemblies"][0]["alias"] == "inputs"


def test_configuration_validation_errors(build_manager, dummy_client):
    app = create_app(build_manager(dummy_client), auth_token=AUTH_TOKEN)
    client = TestClient(app)

    invalid_xml = "<Device><Assemblies><Assembly alias=\"bad\"></Assembly></Assemblies>"
    malformed = client.post(
        "/config/validate",
        headers=_auth_headers(),
        json={"xml": "<Device"},
    )
    assert malformed.status_code == 200
    assert malformed.json()["valid"] is False
    assert malformed.json()["errors"]

    duplicate_alias = client.post(
        "/config/validate",
        headers=_auth_headers(),
        json={
            "xml": """
<DeviceConfiguration>
  <Assemblies>
    <Assembly alias="dup" class_id="0x04" instance_id="1" direction="input" />
    <Assembly alias="dup" class_id="0x04" instance_id="2" direction="output" />
  </Assemblies>
</DeviceConfiguration>
""".strip(),
        },
    )
    assert duplicate_alias.status_code == 200
    assert duplicate_alias.json()["valid"] is False
    assert duplicate_alias.json()["errors"]

    structural = client.post(
        "/config/validate",
        headers=_auth_headers(),
        json={"xml": invalid_xml},
    )
    assert structural.status_code == 200
    assert structural.json()["valid"] is False

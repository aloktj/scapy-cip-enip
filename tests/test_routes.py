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


CIP_CONFIG_XML = """
<cip>
  <identity
    name="CIP Enabled PLC"
    vendorId="101"
    productCode="202"
    majorRev="2"
    minorRev="1"
    serialNumber="0xABCDEF"
  />
  <assemblies>
    <assembly id="InputAlias" dir="in" instanceId="0x64" size="4">
      <members>
        <member name="Status">
          <usint offset="0" />
        </member>
        <member name="Count">
          <uint offset="1" />
        </member>
      </members>
    </assembly>
    <assembly id="OutputAlias" dir="out" instanceId="0x65">
      <usint name="Command" offset="0" />
      <string name="Label" offset="1" length="8">Descriptive label</string>
    </assembly>
  </assemblies>
</cip>
""".strip()


def test_routes_require_authentication(build_manager, dummy_client):
    manager = build_manager(dummy_client)
    app = create_app(manager, auth_token=AUTH_TOKEN)
    client = TestClient(app)

    response = client.post("/sessions")
    assert response.status_code == 401

    response = client.post("/sessions", headers=_auth_headers())
    assert response.status_code == 201
    payload = response.json()
    assert payload["host"] == "127.0.0.1"
    assert payload["port"] == 44818


def test_session_lifecycle_and_commands(build_manager, dummy_client, make_cip_response):
    manager = build_manager(dummy_client)
    app = create_app(manager, auth_token=AUTH_TOKEN)
    client = TestClient(app)

    start = client.post("/sessions", headers=_auth_headers())
    assert start.status_code == 201
    payload = start.json()
    session_id = payload["session_id"]
    assert payload["host"] == "127.0.0.1"
    assert payload["port"] == 44818

    status = client.get(f"/sessions/{session_id}", headers=_auth_headers())
    assert status.status_code == 200
    status_payload = status.json()
    assert status_payload["connection"]["connected"] is True
    assert status_payload["host"] == "127.0.0.1"
    assert status_payload["port"] == 44818

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
    stop_payload = stop.json()
    assert stop_payload["connection"]["connected"] is False
    assert stop_payload["host"] == "127.0.0.1"
    assert stop_payload["port"] == 44818


def test_frontend_assets_served(build_manager, dummy_client, tmp_path):
    manager = build_manager(dummy_client)
    dist_root = tmp_path / "dist"
    assets_root = dist_root / "assets"
    assets_root.mkdir(parents=True)

    index_path = dist_root / "index.html"
    index_path.write_text("<html><head></head><body><script src=\"/assets/app.js\"></script></body></html>")

    asset_path = assets_root / "app.js"
    asset_path.write_text("console.log('ok');")

    app = create_app(manager, auth_token=AUTH_TOKEN, static_root=dist_root)
    client = TestClient(app)

    response = client.get("/ui/")
    assert response.status_code == 200
    assert "app.js" in response.text

    asset_response = client.get("/assets/app.js")
    assert asset_response.status_code == 200
    assert "console.log" in asset_response.text


def test_assembly_runtime_endpoints(build_manager, dummy_client, make_cip_response):
    manager = build_manager(dummy_client)
    app = create_app(manager, auth_token=AUTH_TOKEN)
    client = TestClient(app)

    upload = client.post(
        "/config",
        headers=_auth_headers(),
        json={"xml": CONFIG_XML},
    )
    assert upload.status_code == 201

    start = client.post("/sessions", headers=_auth_headers())
    assert start.status_code == 201
    session_id = start.json()["session_id"]
    assert start.json()["host"] == "127.0.0.1"
    assert start.json()["port"] == 44818

    state = client.get(
        f"/sessions/{session_id}/assemblies/inputs", headers=_auth_headers()
    )
    assert state.status_code == 200
    payload = state.json()
    assert payload["alias"] == "inputs"
    assert payload["status"]["code"] == 0

    dummy_client.queue_response(make_cip_response(status=0))
    write = client.put(
        f"/sessions/{session_id}/assemblies/outputs",
        headers=_auth_headers(),
        json={"payload_hex": "0011223344556677"},
    )
    assert write.status_code == 200
    assert write.json()["code"] == 0
    assert dummy_client.sent[-1][0] == "unit"

    forbidden = client.put(
        f"/sessions/{session_id}/assemblies/inputs",
        headers=_auth_headers(),
        json={"payload_hex": "0000"},
    )
    assert forbidden.status_code == 400

    stop = client.delete(f"/sessions/{session_id}", headers=_auth_headers())
    assert stop.status_code == 200
    assert stop.json()["host"] == "127.0.0.1"
    assert stop.json()["port"] == 44818


def test_sessions_support_custom_host(build_manager, dummy_client):
    manager = build_manager(dummy_client)
    app = create_app(manager, auth_token=AUTH_TOKEN)
    client = TestClient(app)

    start = client.post(
        "/sessions",
        headers=_auth_headers(),
        json={"host": "192.0.2.5", "port": 5000},
    )
    assert start.status_code == 201
    payload = start.json()
    assert payload["host"] == "192.0.2.5"
    assert payload["port"] == 5000
    assert manager.last_endpoint == ("192.0.2.5", 5000)

    stop = client.delete(f"/sessions/{payload['session_id']}", headers=_auth_headers())
    assert stop.status_code == 200
    assert stop.json()["host"] == "192.0.2.5"
    assert stop.json()["port"] == 5000


def test_configuration_upload_and_listing(build_manager, dummy_client):
    manager = build_manager(dummy_client)
    app = create_app(manager, auth_token=AUTH_TOKEN)
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
    manager = build_manager(dummy_client)
    app = create_app(manager, auth_token=AUTH_TOKEN)
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


def test_cip_configuration_support(build_manager, dummy_client):
    app = create_app(build_manager(dummy_client), auth_token=AUTH_TOKEN)
    client = TestClient(app)

    upload = client.post(
        "/config",
        headers=_auth_headers(),
        json={"xml": CIP_CONFIG_XML},
    )
    assert upload.status_code == 201
    payload = upload.json()

    assert payload["identity"]["name"] == "CIP Enabled PLC"
    assert payload["identity"]["vendor"] == "101"
    assert payload["identity"]["product_code"] == "202"
    assert payload["identity"]["revision"] == "2.1"
    assert payload["identity"]["serial_number"] == "0xABCDEF"

    assert len(payload["assemblies"]) == 2

    first = payload["assemblies"][0]
    assert first["alias"] == "InputAlias"
    assert first["class_id"] == 0x04
    assert first["instance_id"] == 0x64
    assert first["direction"] == "input"
    assert first["size"] == 4
    assert [member["name"] for member in first["members"]] == ["Status", "Count"]
    assert first["members"][0]["datatype"] == "usint"
    assert first["members"][0]["offset"] == 0
    assert first["members"][0]["size"] == 1
    assert first["members"][1]["datatype"] == "uint"
    assert first["members"][1]["offset"] == 1
    assert first["members"][1]["size"] == 2

    second = payload["assemblies"][1]
    assert second["alias"] == "OutputAlias"
    assert second["direction"] == "output"
    assert second["size"] is None
    assert [member["name"] for member in second["members"]] == ["Command", "Label"]
    assert second["members"][0]["size"] == 1
    assert second["members"][1]["size"] == 8
    assert second["members"][1]["description"] == "Descriptive label"

    listing = client.get("/config", headers=_auth_headers())
    assert listing.status_code == 200
    catalog = listing.json()
    assert catalog["loaded"] is True
    assert [assembly["alias"] for assembly in catalog["assemblies"]] == [
        "InputAlias",
        "OutputAlias",
    ]

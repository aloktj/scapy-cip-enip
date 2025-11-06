"""Pydantic schemas shared by the web API endpoints."""
from __future__ import annotations

import binascii
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, conint, field_validator, model_validator

from cip import CIP_Path
from services.config_loader import (
    AssemblyDefinition,
    AssemblyMember,
    DeviceConfiguration,
    DeviceIdentity,
)
from services.config_store import ConfigurationState
from services.plc_manager import AssemblySnapshot, CIPStatus, ConnectionStatus

from .orchestrator import SessionDiagnostics

__all__ = [
    "AssemblyQuery",
    "AssemblyReadResponse",
    "AssemblyWriteRequest",
    "CIPPathModel",
    "CIPStatusSchema",
    "CommandRequest",
    "CommandResponse",
    "ConfigurationStatusSchema",
    "ConfigurationUploadRequest",
    "ConfigurationValidationResponse",
    "ConnectionStatusSchema",
    "SessionDiagnosticsResponse",
    "SessionResponse",
]


class CIPStatusSchema(BaseModel):
    code: Optional[int]
    message: Optional[str]

    @classmethod
    def from_status(cls, status: CIPStatus) -> "CIPStatusSchema":
        return cls(code=status.code, message=status.message)


class ConnectionStatusSchema(BaseModel):
    connected: bool
    session_id: int
    enip_connid: int = Field(..., alias="enip_connection_id")
    sequence: int
    last_status: CIPStatusSchema

    @classmethod
    def from_status(cls, status: ConnectionStatus) -> "ConnectionStatusSchema":
        return cls(
            connected=status.connected,
            session_id=status.session_id,
            enip_connection_id=status.enip_connid,
            sequence=status.sequence,
            last_status=CIPStatusSchema.from_status(status.last_status),
        )


class SessionResponse(BaseModel):
    session_id: str
    connection: ConnectionStatusSchema

    @classmethod
    def from_handle(cls, session_id: str, status: ConnectionStatus) -> "SessionResponse":
        return cls(session_id=session_id, connection=ConnectionStatusSchema.from_status(status))


class SessionDiagnosticsResponse(BaseModel):
    session_id: str
    connection: ConnectionStatusSchema
    keep_alive_pattern_hex: str
    keep_alive_active: bool
    last_activity: float

    @classmethod
    def from_report(cls, report: SessionDiagnostics) -> "SessionDiagnosticsResponse":
        return cls(
            session_id=report.session_id,
            connection=ConnectionStatusSchema.from_status(report.connection),
            keep_alive_pattern_hex=report.keep_alive_pattern_hex,
            keep_alive_active=report.keep_alive_active,
            last_activity=report.last_activity_at,
        )


class CIPPathModel(BaseModel):
    class_id: Optional[conint(ge=0)] = None
    instance_id: Optional[conint(ge=0)] = None
    member_id: Optional[conint(ge=0)] = None
    attribute_id: Optional[conint(ge=0)] = None
    symbolic: Optional[str] = Field(None, description="Symbolic path resolved via CIP_Path.make_str")

    @model_validator(mode="after")
    def validate_path(self) -> "CIPPathModel":
        provided = [
            self.class_id,
            self.instance_id,
            self.member_id,
            self.attribute_id,
            self.symbolic,
        ]
        if not any(v is not None for v in provided):
            raise ValueError("At least one CIP path component must be provided")
        return self

    def to_cip_path(self) -> CIP_Path:
        if self.symbolic:
            return CIP_Path.make_str(self.symbolic)
        return CIP_Path.make(
            class_id=self.class_id,
            instance_id=self.instance_id,
            member_id=self.member_id,
            attribute_id=self.attribute_id,
        )


class AssemblyQuery(BaseModel):
    class_id: conint(gt=0)
    instance_id: conint(gt=0)
    total_size: conint(gt=0, le=0x1000) = Field(
        ..., description="Number of bytes expected from the assembly"
    )


class AssemblyReadResponse(BaseModel):
    class_id: int
    instance_id: int
    data_hex: str
    word_values: Optional[list[int]] = None
    timestamp: float
    status: CIPStatusSchema

    @classmethod
    def from_snapshot(cls, snapshot: AssemblySnapshot) -> "AssemblyReadResponse":
        words: Optional[list[int]] = None
        try:
            words = list(snapshot.as_words())
        except Exception:
            words = None
        return cls(
            class_id=snapshot.class_id,
            instance_id=snapshot.instance_id,
            data_hex=binascii.hexlify(snapshot.data).decode("ascii"),
            word_values=words,
            timestamp=snapshot.timestamp,
            status=CIPStatusSchema.from_status(snapshot.last_status),
        )


class AssemblyWriteRequest(BaseModel):
    attribute_id: conint(gt=0)
    value_hex: str = Field(..., description="Hex-encoded payload to write")
    path: Optional[CIPPathModel] = None

    @field_validator("value_hex")
    @classmethod
    def validate_hex(cls, value: str) -> str:
        try:
            if len(value) % 2:
                raise ValueError
            binascii.unhexlify(value)
        except (binascii.Error, ValueError):
            raise ValueError("value_hex must be a valid even-length hexadecimal string")
        return value.lower()

    def value_bytes(self) -> bytes:
        return binascii.unhexlify(self.value_hex)


class CommandRequest(BaseModel):
    service: conint(ge=0, le=0xFF)
    path: CIPPathModel
    payload_hex: Optional[str] = Field(None, description="Optional hex payload")
    transport: Literal["rr", "rr_cm", "rr_mr", "unit"] = "rr_cm"

    @field_validator("payload_hex")
    @classmethod
    def validate_payload(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        try:
            if len(value) % 2:
                raise ValueError
            binascii.unhexlify(value)
        except (binascii.Error, ValueError):
            raise ValueError("payload_hex must be a valid even-length hexadecimal string")
        return value.lower()

    def payload_bytes(self) -> bytes:
        if self.payload_hex is None:
            return b""
        return binascii.unhexlify(self.payload_hex)


class CommandResponse(BaseModel):
    status: CIPStatusSchema
    payload_hex: str

    @classmethod
    def from_result(cls, result_status: CIPStatus, payload: bytes) -> "CommandResponse":
        return cls(
            status=CIPStatusSchema.from_status(result_status),
            payload_hex=binascii.hexlify(payload).decode("ascii"),
        )


class ConfigurationUploadRequest(BaseModel):
    xml: str = Field(..., description="PLC configuration XML payload")


class DeviceIdentitySchema(BaseModel):
    name: Optional[str] = None
    vendor: Optional[str] = None
    product_code: Optional[str] = None
    revision: Optional[str] = None
    serial_number: Optional[str] = None

    @classmethod
    def from_identity(cls, identity: DeviceIdentity) -> "DeviceIdentitySchema":
        return cls(
            name=identity.name,
            vendor=identity.vendor,
            product_code=identity.product_code,
            revision=identity.revision,
            serial_number=identity.serial_number,
        )


class AssemblyMemberSchema(BaseModel):
    name: str
    datatype: Optional[str] = None
    direction: Optional[str] = None
    offset: Optional[int] = None
    size: Optional[int] = None
    description: Optional[str] = None

    @classmethod
    def from_member(cls, member: AssemblyMember) -> "AssemblyMemberSchema":
        return cls(
            name=member.name,
            datatype=member.datatype,
            direction=member.direction,
            offset=member.offset,
            size=member.size,
            description=member.description.strip() if member.description else None,
        )


class AssemblySummarySchema(BaseModel):
    alias: str
    class_id: int
    instance_id: int
    direction: str
    size: Optional[int] = None
    members: List[AssemblyMemberSchema] = Field(default_factory=list)

    @classmethod
    def from_definition(cls, definition: AssemblyDefinition) -> "AssemblySummarySchema":
        return cls(
            alias=definition.alias,
            class_id=definition.class_id,
            instance_id=definition.instance_id,
            direction=definition.direction,
            size=definition.size,
            members=[AssemblyMemberSchema.from_member(member) for member in definition.members],
        )


class ConfigurationStatusSchema(BaseModel):
    loaded: bool
    identity: Optional[DeviceIdentitySchema] = None
    assemblies: List[AssemblySummarySchema] = Field(default_factory=list)

    @classmethod
    def from_state(cls, state: ConfigurationState) -> "ConfigurationStatusSchema":
        if not state.loaded or state.configuration is None:
            return cls(loaded=False, identity=None, assemblies=[])
        return cls.from_configuration(state.configuration, loaded=True)

    @classmethod
    def from_configuration(
        cls, configuration: DeviceConfiguration, *, loaded: bool = False
    ) -> "ConfigurationStatusSchema":
        return cls(
            loaded=loaded,
            identity=DeviceIdentitySchema.from_identity(configuration.identity),
            assemblies=[
                AssemblySummarySchema.from_definition(definition)
                for definition in configuration.assemblies
            ],
        )


class ConfigurationValidationResponse(BaseModel):
    valid: bool
    errors: List[str] = Field(default_factory=list)
    configuration: Optional[ConfigurationStatusSchema] = None

    @model_validator(mode="after")
    def _ensure_valid_payload(self) -> "ConfigurationValidationResponse":
        if not self.valid:
            self.configuration = None
        return self

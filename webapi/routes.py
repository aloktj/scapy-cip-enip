"""FastAPI routes for PLC orchestration and configuration management."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status

from cip import CIP_Path
from services.config_loader import (
    ConfigurationError,
    ConfigurationParseError,
    load_configuration,
)
from services.config_store import ConfigurationStore
from services.io_runtime import (
    AssemblyDirectionError,
    AssemblyNotRegisteredError,
    AssemblyRuntimeError,
)
from services.plc_manager import (
    PLCConnectionError,
    PLCManagerError,
    PLCResponseError,
)

from .dependencies import get_config_store, get_orchestrator, require_token
from .orchestrator import CommandResult, SessionOrchestrator
from .schemas import (
    AssemblyQuery,
    AssemblyReadResponse,
    AssemblyRuntimeResponse,
    AssemblyWriteRequest,
    AssemblyDataWriteRequest,
    CIPStatusSchema,
    CommandRequest,
    CommandResponse,
    ConfigurationStatusSchema,
    ConfigurationUploadRequest,
    ConfigurationValidationResponse,
    SessionDiagnosticsResponse,
    SessionResponse,
    SessionStartRequest,
)

api_router = APIRouter()

sessions_router = APIRouter(
    prefix="/sessions", tags=["sessions"], dependencies=[Depends(require_token)]
)

config_router = APIRouter(
    prefix="/config", tags=["configuration"], dependencies=[Depends(require_token)]
)


@sessions_router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def start_session(
    request: Request,
    payload: SessionStartRequest | None = Body(default=None),
    orchestrator: SessionOrchestrator = Depends(get_orchestrator),
) -> SessionResponse:
    try:
        handle = orchestrator.start_session(
            host=payload.host if payload else None,
            port=payload.port if payload else None,
        )
    except PLCConnectionError as exc:
        request.state.enip_error = str(exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except PLCResponseError as exc:
        request.state.cip_status = exc.status
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except PLCManagerError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    request.state.cip_status = handle.status.last_status
    return SessionResponse.from_handle(handle.session_id, handle.status)


@sessions_router.delete("/{session_id}", response_model=SessionResponse)
def stop_session(
    session_id: str,
    request: Request,
    orchestrator: SessionOrchestrator = Depends(get_orchestrator),
) -> SessionResponse:
    try:
        connection = orchestrator.stop_session(session_id)
    except PLCManagerError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PLCConnectionError as exc:
        request.state.enip_error = str(exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except PLCResponseError as exc:
        request.state.cip_status = exc.status
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    request.state.cip_status = connection.last_status
    return SessionResponse.from_handle(session_id, connection)


@sessions_router.get("/{session_id}", response_model=SessionResponse)
def get_session(
    session_id: str,
    request: Request,
    orchestrator: SessionOrchestrator = Depends(get_orchestrator),
) -> SessionResponse:
    try:
        status = orchestrator.get_status(session_id)
    except PLCManagerError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    request.state.cip_status = status.last_status
    return SessionResponse.from_handle(session_id, status)


@sessions_router.get("/{session_id}/diagnostics", response_model=SessionDiagnosticsResponse)
def session_diagnostics(
    session_id: str,
    request: Request,
    orchestrator: SessionOrchestrator = Depends(get_orchestrator),
) -> SessionDiagnosticsResponse:
    try:
        report = orchestrator.get_diagnostics(session_id)
    except PLCManagerError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    request.state.cip_status = report.connection.last_status
    return SessionDiagnosticsResponse.from_report(report)


@sessions_router.get("/{session_id}/assemblies", response_model=AssemblyReadResponse)
def read_assembly(
    session_id: str,
    request: Request,
    query: AssemblyQuery = Depends(),
    orchestrator: SessionOrchestrator = Depends(get_orchestrator),
) -> AssemblyReadResponse:
    try:
        snapshot = orchestrator.read_assembly(
            session_id,
            class_id=query.class_id,
            instance_id=query.instance_id,
            total_size=query.total_size,
        )
    except PLCResponseError as exc:
        request.state.cip_status = exc.status
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except PLCConnectionError as exc:
        request.state.enip_error = str(exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except PLCManagerError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    request.state.cip_status = snapshot.last_status
    return AssemblyReadResponse.from_snapshot(snapshot)


@sessions_router.patch("/{session_id}/assemblies/{path}", response_model=CIPStatusSchema)
def update_assembly(
    session_id: str,
    path: str,
    payload: AssemblyWriteRequest,
    request: Request,
    orchestrator: SessionOrchestrator = Depends(get_orchestrator),
) -> CIPStatusSchema:
    try:
        cip_path = payload.path.to_cip_path() if payload.path else None
        if cip_path is None:
            cip_path = CIP_Path.make_str(path)
        status_obj = orchestrator.write_attribute(
            session_id,
            path=cip_path,
            attribute_id=int(payload.attribute_id),
            value=payload.value_bytes(),
        )
    except PLCResponseError as exc:
        request.state.cip_status = exc.status
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except PLCConnectionError as exc:
        request.state.enip_error = str(exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except PLCManagerError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    request.state.cip_status = status_obj
    return CIPStatusSchema.from_status(status_obj)


@sessions_router.get(
    "/{session_id}/assemblies/{alias}", response_model=AssemblyRuntimeResponse
)
def get_assembly_state(
    session_id: str,
    alias: str,
    request: Request,
    orchestrator: SessionOrchestrator = Depends(get_orchestrator),
) -> AssemblyRuntimeResponse:
    try:
        view = orchestrator.get_assembly_state(session_id, alias)
    except PLCManagerError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AssemblyNotRegisteredError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AssemblyRuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    request.state.cip_status = view.status
    return AssemblyRuntimeResponse.from_view(view)


@sessions_router.put(
    "/{session_id}/assemblies/{alias}", response_model=CIPStatusSchema
)
def write_assembly(
    session_id: str,
    alias: str,
    payload: AssemblyDataWriteRequest,
    request: Request,
    orchestrator: SessionOrchestrator = Depends(get_orchestrator),
) -> CIPStatusSchema:
    try:
        status_obj = orchestrator.write_assembly(session_id, alias, payload.value_bytes())
    except AssemblyNotRegisteredError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AssemblyDirectionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except PLCResponseError as exc:
        request.state.cip_status = exc.status
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except PLCManagerError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except AssemblyRuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    request.state.cip_status = status_obj
    return CIPStatusSchema.from_status(status_obj)


@sessions_router.post("/{session_id}/commands", response_model=CommandResponse)
def execute_command(
    session_id: str,
    payload: CommandRequest,
    request: Request,
    orchestrator: SessionOrchestrator = Depends(get_orchestrator),
) -> CommandResponse:
    try:
        result: CommandResult = orchestrator.send_command(
            session_id,
            service=int(payload.service),
            path=payload.path.to_cip_path(),
            payload=payload.payload_bytes(),
            transport=payload.transport,
        )
    except PLCResponseError as exc:
        request.state.cip_status = exc.status
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except PLCConnectionError as exc:
        request.state.enip_error = str(exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except PLCManagerError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    request.state.cip_status = result.status
    return CommandResponse.from_result(result.status, result.payload)


@config_router.post("", response_model=ConfigurationStatusSchema, status_code=status.HTTP_201_CREATED)
def upload_configuration(
    payload: ConfigurationUploadRequest,
    store: ConfigurationStore = Depends(get_config_store),
    orchestrator: SessionOrchestrator = Depends(get_orchestrator),
) -> ConfigurationStatusSchema:
    try:
        configuration = load_configuration(payload.xml)
    except ConfigurationParseError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    state = store.load(configuration)
    orchestrator.apply_configuration(configuration)
    return ConfigurationStatusSchema.from_state(state)


@config_router.post("/validate", response_model=ConfigurationValidationResponse)
def validate_configuration(payload: ConfigurationUploadRequest) -> ConfigurationValidationResponse:
    try:
        configuration = load_configuration(payload.xml)
    except ConfigurationParseError as exc:
        return ConfigurationValidationResponse(valid=False, errors=[str(exc)])
    except ConfigurationError as exc:
        return ConfigurationValidationResponse(valid=False, errors=[str(exc)])

    return ConfigurationValidationResponse(
        valid=True,
        errors=[],
        configuration=ConfigurationStatusSchema.from_configuration(configuration),
    )


@config_router.get("", response_model=ConfigurationStatusSchema)
def get_configuration(store: ConfigurationStore = Depends(get_config_store)) -> ConfigurationStatusSchema:
    return ConfigurationStatusSchema.from_state(store.get_state())


api_router.include_router(sessions_router)
api_router.include_router(config_router)

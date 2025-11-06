"""FastAPI routes for PLC orchestration."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from cip import CIP_Path
from services.plc_manager import (
    PLCConnectionError,
    PLCManagerError,
    PLCResponseError,
)

from .dependencies import get_orchestrator
from .orchestrator import CommandResult, SessionOrchestrator
from .schemas import (
    AssemblyQuery,
    AssemblyReadResponse,
    AssemblyWriteRequest,
    CIPStatusSchema,
    CommandRequest,
    CommandResponse,
    SessionDiagnosticsResponse,
    SessionResponse,
)

api_router = APIRouter(prefix="/sessions", tags=["sessions"])


@api_router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def start_session(
    request: Request,
    orchestrator: SessionOrchestrator = Depends(get_orchestrator),
) -> SessionResponse:
    try:
        handle = orchestrator.start_session()
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


@api_router.delete("/{session_id}", response_model=SessionResponse)
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


@api_router.get("/{session_id}", response_model=SessionResponse)
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


@api_router.get("/{session_id}/diagnostics", response_model=SessionDiagnosticsResponse)
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


@api_router.get("/{session_id}/assemblies", response_model=AssemblyReadResponse)
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


@api_router.patch("/{session_id}/assemblies/{path}", response_model=CIPStatusSchema)
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


@api_router.post("/{session_id}/commands", response_model=CommandResponse)
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

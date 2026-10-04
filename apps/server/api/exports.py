from typing import Annotated, Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse, Response

from apps.server.api.dependencies import identity_dependencies
from packages.contracts import Error
from packages.contracts.reports import ExportAction, ExportCreate, ExportView


def export_router(service):
    router = APIRouter(
        prefix="/api/v1/exports",
        tags=["exports"],
        responses={c: {"model": Error} for c in [401, 403, 404, 409, 422, 503]},
    )
    token, authorization = identity_dependencies(service.identity)

    @router.post("", response_model=ExportView, status_code=201)
    def create(
        payload: ExportCreate,
        request: Request,
        key: Annotated[UUID, Header(alias="Idempotency-Key")],
        access=Depends(token),
    ):
        result = service.create(access, key, payload, request.state.request_id)
        return JSONResponse(result.body, status_code=result.http_status)

    @router.get("/{job_id}", response_model=ExportView)
    def read(job_id: UUID, auth=Depends(authorization)):
        return service.read(auth, job_id)

    @router.post("/{job_id}/{operation}", response_model=ExportView)
    def action(
        job_id: UUID,
        operation: Literal["cancel", "retry"],
        payload: ExportAction,
        request: Request,
        key: Annotated[UUID, Header(alias="Idempotency-Key")],
        access=Depends(token),
    ):
        result = service.action(access, key, job_id, operation, payload, request.state.request_id)
        return JSONResponse(result.body, status_code=result.http_status)

    @router.get(
        "/{job_id}/download",
        response_class=Response,
        responses={
            200: {"content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}}
        },
    )
    def download(job_id: UUID, access=Depends(token)):
        data, name, mime = service.download(access, job_id)
        return Response(
            data,
            media_type=mime,
            headers={
                "Content-Disposition": "attachment; filename*=UTF-8''" + quote(name),
                "X-Content-Type-Options": "nosniff",
            },
        )

    return router

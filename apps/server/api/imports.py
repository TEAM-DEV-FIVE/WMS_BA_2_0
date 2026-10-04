from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response

from apps.server.api.dependencies import identity_dependencies
from apps.server.application.import_parser import error_csv
from apps.server.application.imports import authorize_kind
from apps.server.domain.errors import DomainError
from apps.server.infrastructure.file_storage import safe_name
from packages.contracts import Error
from packages.contracts.imports import (
    FileView,
    ImportAck,
    ImportAction,
    ImportCommit,
    ImportCreate,
    ImportKind,
    ImportRows,
    ImportView,
)


def import_router(service):
    router = APIRouter(
        prefix="/api/v1",
        tags=["imports"],
        responses={c: {"model": Error} for c in [401, 403, 404, 409, 413, 422, 503]},
    )
    token, authorization = identity_dependencies(service.identity)

    @router.post(
        "/files",
        response_model=FileView,
        status_code=201,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
            }
        },
    )
    async def upload(
        request: Request,
        kind: ImportKind,
        access: Annotated[str, Depends(token)],
        key: Annotated[UUID, Header(alias="Idempotency-Key")],
        filename: Annotated[str, Header(alias="X-File-Name")],
        warehouse_id: UUID | None = None,
    ):
        safe_name(filename)

        def check():
            with service.identity.engine.begin() as c:
                authorize_kind(service.identity.authorization(c, access), kind, warehouse_id)

        await run_in_threadpool(check)
        limit = service.storage.settings.max_file_bytes
        length = request.headers.get("content-length")
        if length and (not length.isdecimal() or int(length) > limit):
            raise DomainError("FILE_LIMIT", "Tệp vượt hạn mức upload.")
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > limit:
                raise DomainError("FILE_LIMIT", "Tệp vượt hạn mức upload.")
            data.extend(chunk)
        result = await run_in_threadpool(
            service.upload, access, key, kind, warehouse_id, filename, bytes(data), request.state.request_id
        )
        return JSONResponse(result.body, status_code=result.http_status)

    @router.get("/files/{file_id}", response_model=FileView)
    def metadata(file_id: UUID, auth=Depends(authorization)):
        return service.file_view(service.file(auth, file_id))

    @router.get(
        "/files/{file_id}/download",
        response_class=Response,
        responses={
            200: {"content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}}
        },
    )
    def download(file_id: UUID, access: Annotated[str, Depends(token)]):
        with service.identity.engine.begin() as c:
            file = service.file(service.identity.authorization(c, access), file_id)
            if not file["ready"]:
                raise DomainError("FILE_UNAVAILABLE", "Upload chưa hoàn tất.")
        data = service.storage.read(file["storage_key"], file["sha256"], file["size_bytes"])
        # Recheck after file I/O so a revoke during the read cannot bypass authorization.
        with service.identity.engine.begin() as c:
            service.file(service.identity.authorization(c, access), file_id)
        return Response(
            data,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": "attachment; filename*=UTF-8''"
                + quote(file["original_name"], safe=""),
                "X-Content-Type-Options": "nosniff",
            },
        )

    @router.post("/imports", response_model=ImportAck, status_code=201)
    def create(
        payload: ImportCreate,
        request: Request,
        access: Annotated[str, Depends(token)],
        key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ):
        result = service.create(access, key, payload, request.state.request_id)
        return JSONResponse(result.body, status_code=result.http_status)

    @router.get("/imports/{job_id}", response_model=ImportView)
    def read(job_id: UUID, auth=Depends(authorization)):
        return service.read(auth, job_id)

    @router.get("/imports/{job_id}/rows", response_model=ImportRows)
    def rows(
        job_id: UUID,
        after: int = Query(default=0, ge=0),
        limit: int = Query(default=50, ge=1, le=200),
        auth=Depends(authorization),
    ):
        return service.rows(auth, job_id, after, limit)

    @router.get(
        "/imports/{job_id}/errors",
        response_class=Response,
        responses={200: {"content": {"text/csv": {"schema": {"type": "string"}}}}},
    )
    def errors(job_id: UUID, auth=Depends(authorization)):
        job = service.job(auth, job_id)
        return Response(
            error_csv(job["errors"]),
            media_type="text/csv",
            headers={
                "Content-Disposition": 'attachment; filename="import-errors.csv"',
                "X-Content-Type-Options": "nosniff",
            },
        )

    @router.post("/imports/{job_id}/commit", response_model=ImportAck)
    def commit(
        job_id: UUID,
        payload: ImportCommit,
        request: Request,
        access: Annotated[str, Depends(token)],
        key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ):
        result = service.action(access, key, job_id, "commit", payload, request.state.request_id)
        return JSONResponse(result.body, status_code=result.http_status)

    @router.post("/imports/{job_id}/cancel", response_model=ImportAck)
    def cancel(
        job_id: UUID,
        payload: ImportAction,
        request: Request,
        access: Annotated[str, Depends(token)],
        key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ):
        result = service.action(access, key, job_id, "cancel", payload, request.state.request_id)
        return JSONResponse(result.body, status_code=result.http_status)

    @router.post("/imports/{job_id}/validate", response_model=ImportAck)
    def validate(
        job_id: UUID,
        payload: ImportAction,
        request: Request,
        access: Annotated[str, Depends(token)],
        key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ):
        result = service.action(access, key, job_id, "validate", payload, request.state.request_id)
        return JSONResponse(result.body, status_code=result.http_status)

    return router

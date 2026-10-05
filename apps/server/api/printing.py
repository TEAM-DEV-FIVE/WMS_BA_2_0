from typing import Annotated, Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text

from apps.server.api.dependencies import identity_dependencies
from apps.server.application.scanner import resolve
from packages.contracts import Error
from packages.contracts.printing import (
    PrintAction,
    PrintCreate,
    PrintJob,
    ScanInput,
    SpoolBegin,
    SpoolResult,
    Template,
)


def print_router(service):
    router = APIRouter(
        prefix="/api/v1/printing",
        tags=["prints"],
        responses={c: {"model": Error} for c in [401, 403, 404, 409, 422, 503]},
    )
    token, authorization = identity_dependencies(service.identity)

    @router.get("/sources")
    def sources(
        template: Template,
        warehouse_id: UUID,
        q: str = Query(default="", max_length=160),
        auth=Depends(authorization),
    ):
        auth.require("print.execute", warehouse_id)
        if template in {"RECEIPT", "ISSUE", "TRANSFER"}:
            result = service.orders.listing(auth, template, warehouse_id, query=q, limit=50)
            return [dict(id=str(r.id), number=r.number, version=r.version) for r in result["items"]]
        if template == "COUNT":
            result = service.counting.listing(auth, warehouse_id, limit=50)
            return [
                dict(id=str(r["id"]), number=r["number"], version=r["version"])
                for r in result["items"]
                if q.casefold() in r["number"].casefold()
            ]
        auth.require("master.read")
        sql = (
            "SELECT id,sku AS number,name,version FROM wms.product WHERE is_active"
            if template == "PRODUCT_LABEL"
            else "SELECT id,code AS number,name,version FROM wms.location WHERE is_active AND warehouse_id=:wh"
        )
        return [
            dict(r)
            for r in auth.connection.execute(
                text(
                    "SELECT * FROM ("
                    + sql
                    + ") s WHERE strpos(lower(number),lower(:q))>0 ORDER BY number LIMIT 50"
                ),
                dict(wh=warehouse_id, q=q),
            ).mappings()
        ]

    @router.post("/scan")
    def scan(
        payload: ScanInput, key: Annotated[UUID, Header(alias="Idempotency-Key")], auth=Depends(authorization)
    ):
        return resolve(service, auth, payload)

    @router.post("", response_model=PrintJob, status_code=201)
    def create(
        payload: PrintCreate,
        request: Request,
        key: Annotated[UUID, Header(alias="Idempotency-Key")],
        access=Depends(token),
    ):
        result = service.create(access, key, payload, request.state.request_id)
        return JSONResponse(result.body, status_code=result.http_status)

    @router.get("/{job_id}", response_model=PrintJob)
    def read(job_id: UUID, auth=Depends(authorization)):
        return service.read(auth, job_id)

    @router.post("/{job_id}/spool", response_model=PrintJob)
    def spool(
        job_id: UUID,
        payload: SpoolBegin,
        request: Request,
        key: Annotated[UUID, Header(alias="Idempotency-Key")],
        access=Depends(token),
    ):
        result = service.action(access, key, job_id, "spool", payload, request.state.request_id)
        return JSONResponse(result.body, status_code=result.http_status)

    @router.post("/{job_id}/result", response_model=PrintJob)
    def outcome(
        job_id: UUID,
        payload: SpoolResult,
        request: Request,
        key: Annotated[UUID, Header(alias="Idempotency-Key")],
        access=Depends(token),
    ):
        result = service.action(access, key, job_id, "result", payload, request.state.request_id)
        return JSONResponse(result.body, status_code=result.http_status)

    @router.get(
        "/{job_id}/download",
        response_class=Response,
        responses={
            200: {"content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}}
        },
    )
    def download(job_id: UUID, attempt_id: UUID | None = None, access=Depends(token)):
        data, name, mime = service.download(access, job_id, attempt_id)
        return Response(
            data,
            media_type=mime,
            headers={
                "Content-Disposition": "attachment; filename*=UTF-8''" + quote(name),
                "X-Content-Type-Options": "nosniff",
            },
        )

    @router.post("/{job_id}/{operation}", response_model=PrintJob)
    def action(
        job_id: UUID,
        operation: Literal["cancel", "retry", "reprint"],
        payload: PrintAction,
        request: Request,
        key: Annotated[UUID, Header(alias="Idempotency-Key")],
        access=Depends(token),
    ):
        result = service.action(access, key, job_id, operation, payload, request.state.request_id)
        return JSONResponse(result.body, status_code=result.http_status)

    return router

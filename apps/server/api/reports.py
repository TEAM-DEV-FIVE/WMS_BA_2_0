from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from apps.server.api.dependencies import identity_dependencies
from packages.contracts import Error
from packages.contracts.reports import ReportCode, ReportCriteria, ReportPage, ReportSnapshot


def report_router(service):
    router = APIRouter(
        prefix="/api/v1/reports",
        tags=["reports"],
        responses={c: {"model": Error} for c in [401, 403, 404, 409, 422, 503]},
    )
    token, authorization = identity_dependencies(service.identity)

    @router.get("/lookups/{kind}")
    def lookup(
        kind: Literal["product", "owner", "location"],
        warehouse_id: UUID,
        code: str = Query(min_length=1, max_length=100),
        auth=Depends(authorization),
    ):
        auth.require("report.read", warehouse_id)
        auth.require("ownership.read", warehouse_id)
        tables = {
            "product": ("product", "sku"),
            "owner": ("stock_owner", "code"),
            "location": ("location", "code"),
        }
        table, column = tables[kind]
        scope = (
            " AND warehouse_id=:warehouse AND kind IN ('STORAGE','RECEIVING','QUARANTINE','SHIPPING')"
            if kind == "location"
            else ""
        )
        return [
            dict(r)
            for r in auth.connection.execute(
                text(f"SELECT id,{column} AS code,name FROM wms.{table} WHERE {column}=:code" + scope),
                dict(code=code, warehouse=warehouse_id),
            ).mappings()
        ]

    @router.post("/{code}/snapshots", response_model=ReportSnapshot, status_code=201)
    def create(
        code: ReportCode,
        payload: ReportCriteria,
        request: Request,
        key: Annotated[UUID, Header(alias="Idempotency-Key")],
        access=Depends(token),
    ):
        result = service.create(access, key, code, payload, request.state.request_id)
        return JSONResponse(result.body, status_code=result.http_status)

    @router.get("/snapshots/{snapshot_id}", response_model=ReportPage)
    def page(
        snapshot_id: UUID,
        after: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=200),
        auth=Depends(authorization),
    ):
        return service.page(auth, snapshot_id, after, limit)

    return router

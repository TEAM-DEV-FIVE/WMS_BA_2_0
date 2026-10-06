from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse

from apps.server.api.dependencies import identity_dependencies
from packages.contracts import Error
from packages.contracts.traceability import OwnershipBalance, SerialWarranty, WarrantyInput, WarrantyResult


def traceability_router(service):
    router = APIRouter(prefix="/api/v1", tags=["traceability"],
                       responses={code: {"model": Error} for code in (401, 403, 404, 409, 422, 503)})
    token, authorization = identity_dependencies(service.identity)

    @router.get("/stock-ownership", response_model=OwnershipBalance)
    def ownership(warehouse_id: UUID, location_id: UUID, stock_item_id: UUID, auth=Depends(authorization)):
        return service.ownership(auth, warehouse_id, location_id, stock_item_id)

    @router.get("/serials/lookup", response_model=list[SerialWarranty])
    def lookup(warehouse_id: UUID, code: str = Query(min_length=1, max_length=160),
               sku: str | None = Query(default=None, min_length=1, max_length=80), auth=Depends(authorization)):
        return service.lookup(auth, warehouse_id, code, sku)

    @router.get("/serials/{serial_id}/warranty", response_model=SerialWarranty)
    def warranty(serial_id: UUID, warehouse_id: UUID, auth=Depends(authorization)):
        return service.warranty(auth, serial_id, warehouse_id)

    @router.post("/serials/{serial_id}/warranty-records", response_model=WarrantyResult, status_code=201)
    def record(serial_id: UUID, payload: WarrantyInput, request: Request, access: Annotated[str, Depends(token)],
               key: Annotated[UUID, Header(alias="Idempotency-Key")]):
        result = service.record_warranty(access, key, serial_id, payload, request.state.request_id)
        return JSONResponse(result.body, status_code=result.http_status)

    return router

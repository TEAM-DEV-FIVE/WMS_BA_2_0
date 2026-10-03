from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse

from apps.server.api.dependencies import identity_dependencies
from packages.contracts import Error
from packages.contracts.orders import OrderPage, OrderResult, OrderStatus
from packages.contracts.receipts import (
    OperationView,
    ReceiptInput,
    ReceiptPost,
    ReceiptPostResult,
    ReceiptUpdate,
    ReceiptView,
)


def receipt_router(service):
    router = APIRouter(
        prefix="/api/v1",
        tags=["receipts"],
        responses={c: {"model": Error} for c in (401, 403, 404, 409, 422, 503)},
    )
    token, authorization = identity_dependencies(service.identity)

    @router.get("/receipts", response_model=OrderPage)
    def listing(
        warehouse_id: UUID,
        status: OrderStatus | None = None,
        after: UUID | None = None,
        limit: int = Query(default=50, ge=1, le=200),
        auth=Depends(authorization),
    ):
        return service.orders.listing(auth, "RECEIPT", warehouse_id, status, after, limit, consignment_only=False)

    @router.get("/receipts/locations")
    def locations(warehouse_id: UUID, auth=Depends(authorization)):
        return service.locations(auth, warehouse_id)

    @router.get("/receipts/{document_id}", response_model=ReceiptView)
    def read(document_id: UUID, auth=Depends(authorization)):
        return service.read(auth, document_id)

    @router.post("/receipts", response_model=OrderResult, status_code=201)
    def create(
        payload: ReceiptInput,
        request: Request,
        access: Annotated[str, Depends(token)],
        key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ):
        result = service.write(access, key, payload, request.state.request_id)
        return JSONResponse(result.body, status_code=result.http_status)

    @router.put("/receipts/{document_id}", response_model=OrderResult)
    def update(
        document_id: UUID,
        payload: ReceiptUpdate,
        request: Request,
        access: Annotated[str, Depends(token)],
        key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ):
        result = service.write(access, key, payload, request.state.request_id, document_id)
        return JSONResponse(result.body, status_code=result.http_status)

    @router.post("/receipts/{document_id}/post", response_model=ReceiptPostResult)
    def post(
        document_id: UUID,
        payload: ReceiptPost,
        request: Request,
        access: Annotated[str, Depends(token)],
        key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ):
        result = service.post(access, key, document_id, payload, request.state.request_id)
        return JSONResponse(result.body, status_code=result.http_status)

    @router.get("/operations/{key}", response_model=OperationView)
    def operation(key: UUID, auth=Depends(authorization)):
        return service.operation(auth, key)

    return router

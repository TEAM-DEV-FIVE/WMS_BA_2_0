from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse

from apps.server.api.dependencies import identity_dependencies
from packages.contracts import Error
from packages.contracts.moves import MoveLocationPage, MoveStockPage
from packages.contracts.orders import OrderPage, OrderStatus
from packages.contracts.transfers import (
    TransferAssigneePage,
    TransferDiscrepancy,
    TransferDispatch,
    TransferEvidencePage,
    TransferHistoryPage,
    TransferInput,
    TransferLossInput,
    TransferPostResult,
    TransferReceive,
    TransferResult,
    TransferUpdate,
    TransferView,
)


def transfer_router(service):
    router = APIRouter(
        prefix="/api/v1/transfers",
        tags=["transfers"],
        responses={code: {"model": Error} for code in (401, 403, 404, 409, 422, 503)},
    )
    token, authorization = identity_dependencies(service.identity)

    @router.get("", response_model=OrderPage)
    def listing(
        warehouse_id: UUID,
        status: OrderStatus | None = None,
        after: UUID | None = None,
        limit: int = Query(default=50, ge=1, le=200),
        auth=Depends(authorization),
    ):
        return service.listing(auth, warehouse_id, status, after, limit)

    @router.get("/stock", response_model=MoveStockPage)
    def stock(
        warehouse_id: UUID,
        after: UUID | None = None,
        limit: int = Query(default=50, ge=1, le=200),
        auth=Depends(authorization),
    ):
        return service.orders.moves.stock(auth, warehouse_id, after, limit)

    @router.get("/locations", response_model=MoveLocationPage)
    def locations(
        warehouse_id: UUID,
        after: UUID | None = None,
        limit: int = Query(default=50, ge=1, le=200),
        auth=Depends(authorization),
    ):
        return service.orders.moves.locations(auth, warehouse_id, after, limit)

    @router.get("/operations/{key}", response_model=TransferPostResult)
    def operation(key: UUID, auth=Depends(authorization)):
        return service.operation(auth, key)

    @router.get("/{doc_id}", response_model=TransferView)
    def read(doc_id: UUID, auth=Depends(authorization)):
        return service.read(auth, doc_id)

    @router.get("/{doc_id}/history", response_model=TransferHistoryPage)
    def history(
        doc_id: UUID,
        after: UUID | None = None,
        limit: int = Query(default=50, ge=1, le=200),
        auth=Depends(authorization),
    ):
        return service.history(auth, doc_id, after, limit)

    @router.post("", response_model=TransferResult, status_code=201)
    def create(
        payload: TransferInput,
        request: Request,
        access: Annotated[str, Depends(token)],
        key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ):
        result = service.write(access, key, payload, request.state.request_id)
        return JSONResponse(result.body, status_code=result.http_status)

    @router.put("/{doc_id}", response_model=TransferResult)
    def update(
        doc_id: UUID,
        payload: TransferUpdate,
        request: Request,
        access: Annotated[str, Depends(token)],
        key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ):
        result = service.write(access, key, payload, request.state.request_id, doc_id)
        return JSONResponse(result.body, status_code=result.http_status)

    @router.post("/{doc_id}/dispatch", response_model=TransferPostResult)
    def dispatch(
        doc_id: UUID,
        payload: TransferDispatch,
        request: Request,
        access: Annotated[str, Depends(token)],
        key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ):
        result = service.post(access, key, doc_id, payload, request.state.request_id, "DISPATCH")
        return JSONResponse(result.body, status_code=result.http_status)

    @router.post("/{doc_id}/receive", response_model=TransferPostResult)
    def receive(
        doc_id: UUID,
        payload: TransferReceive,
        request: Request,
        access: Annotated[str, Depends(token)],
        key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ):
        result = service.post(access, key, doc_id, payload, request.state.request_id, "ARRIVE")
        return JSONResponse(result.body, status_code=result.http_status)

    @router.post("/{doc_id}/discrepancies", response_model=TransferResult)
    def discrepancy(
        doc_id: UUID,
        payload: TransferDiscrepancy,
        request: Request,
        access: Annotated[str, Depends(token)],
        key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ):
        result = service.discrepancy(access, key, doc_id, payload, request.state.request_id)
        return JSONResponse(result.body, status_code=result.http_status)

    @router.post("/{doc_id}/adjustments", response_model=TransferResult, status_code=201)
    def loss(
        doc_id: UUID,
        payload: TransferLossInput,
        request: Request,
        access: Annotated[str, Depends(token)],
        key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ):
        result = service.create_loss(access, key, doc_id, payload, request.state.request_id)
        return JSONResponse(result.body, status_code=result.http_status)

    @router.post("/{doc_id}/loss-post", response_model=TransferPostResult)
    def loss_post(
        doc_id: UUID,
        payload: TransferDispatch,
        request: Request,
        access: Annotated[str, Depends(token)],
        key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ):
        result = service.post(access, key, doc_id, payload, request.state.request_id, "ADJUST")
        return JSONResponse(result.body, status_code=result.http_status)

    @router.get("/{doc_id}/assignees", response_model=TransferAssigneePage)
    def assignees(
        doc_id: UUID,
        after: UUID | None = None,
        limit: int = Query(default=100, ge=1, le=200),
        auth=Depends(authorization),
    ):
        return service.assignees(auth, doc_id, after, limit)

    @router.get("/{doc_id}/discrepancies", response_model=TransferEvidencePage)
    def evidences(
        doc_id: UUID,
        after: UUID | None = None,
        limit: int = Query(default=50, ge=1, le=200),
        auth=Depends(authorization),
    ):
        return service.evidences(auth, doc_id, after, limit)

    @router.get("/{doc_id}/adjustments", response_model=OrderPage)
    def adjustments(
        doc_id: UUID,
        after: UUID | None = None,
        limit: int = Query(default=50, ge=1, le=200),
        auth=Depends(authorization),
    ):
        return service.adjustments(auth, doc_id, after, limit)

    return router

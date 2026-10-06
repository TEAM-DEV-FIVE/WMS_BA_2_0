from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse

from apps.server.api.dependencies import identity_dependencies
from packages.contracts import Error
from packages.contracts.orders import OrderPage, OrderStatus
from packages.contracts.reversals import (
    ReversalInput,
    ReversalOperation,
    ReversalPost,
    ReversalPreview,
    ReversalResult,
    ReversalSourcePage,
    ReversalUpdate,
    ReversalView,
)


def reversal_router(service):
    router = APIRouter(prefix="/api/v1", tags=["reversals"],
                       responses={code: {"model": Error} for code in (401, 403, 404, 409, 422, 503)})
    token, authorization = identity_dependencies(service.identity)

    @router.get("/reversals", response_model=OrderPage)
    def listing(warehouse_id: UUID, status: OrderStatus | None = None, after: UUID | None = None,
                limit: int = Query(default=50, ge=1, le=200), auth=Depends(authorization)):
        return service.listing(auth, warehouse_id, status, after, limit)

    @router.get("/reversals/sources", response_model=ReversalSourcePage)
    def sources(warehouse_id: UUID, after: UUID | None = None,
                limit: int = Query(default=50, ge=1, le=200), auth=Depends(authorization)):
        return service.sources(auth, warehouse_id, after, limit)

    @router.get("/transactions/{transaction_id}/reversal-preview", response_model=ReversalPreview)
    def preview(transaction_id: UUID, business_date: date, auth=Depends(authorization)):
        return service.preview(auth, transaction_id, business_date)

    @router.get("/reversals/operations/{key}", response_model=ReversalOperation)
    def operation(key: UUID, auth=Depends(authorization)):
        return service.operation(auth, key)

    @router.get("/reversals/{doc_id}", response_model=ReversalView)
    def read(doc_id: UUID, auth=Depends(authorization)):
        return service.read(auth, doc_id)

    @router.post("/reversals", response_model=ReversalResult, status_code=201)
    def create(payload: ReversalInput, request: Request, access: Annotated[str, Depends(token)],
               key: Annotated[UUID, Header(alias="Idempotency-Key")]):
        result = service.write(access, key, payload, request.state.request_id)
        return JSONResponse(result.body, status_code=result.http_status)

    @router.put("/reversals/{doc_id}", response_model=ReversalResult)
    def update(doc_id: UUID, payload: ReversalUpdate, request: Request, access: Annotated[str, Depends(token)],
               key: Annotated[UUID, Header(alias="Idempotency-Key")]):
        result = service.write(access, key, payload, request.state.request_id, doc_id)
        return JSONResponse(result.body, status_code=result.http_status)

    @router.post("/reversals/{doc_id}/post", response_model=ReversalResult)
    def post(doc_id: UUID, payload: ReversalPost, request: Request, access: Annotated[str, Depends(token)],
             key: Annotated[UUID, Header(alias="Idempotency-Key")]):
        result = service.post(access, key, doc_id, payload, request.state.request_id)
        return JSONResponse(result.body, status_code=result.http_status)

    return router

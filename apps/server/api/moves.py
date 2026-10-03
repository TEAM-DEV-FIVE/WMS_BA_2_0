from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse

from apps.server.api.dependencies import identity_dependencies
from packages.contracts import Error
from packages.contracts.moves import (
    MoveInput,
    MoveLocationPage,
    MovePost,
    MovePostResult,
    MoveStockPage,
    MoveUpdate,
    MoveView,
)
from packages.contracts.orders import OrderPage, OrderResult, OrderStatus
from packages.contracts.receipts import OperationView


def move_router(service):
    router = APIRouter(prefix="/api/v1/moves", tags=["moves"],
                       responses={code: {"model": Error} for code in (401, 403, 404, 409, 422, 503)})
    token, authorization = identity_dependencies(service.identity)

    @router.get("", response_model=OrderPage)
    def listing(warehouse_id: UUID, status: OrderStatus | None = None, after: UUID | None = None,
                limit: int = Query(default=50, ge=1, le=200), auth=Depends(authorization)):
        return service.orders.listing(auth, "INTERNAL_MOVE", warehouse_id, status, after, limit)

    @router.get("/locations", response_model=MoveLocationPage)
    def locations(warehouse_id: UUID, after: UUID | None = None, limit: int = Query(default=50, ge=1, le=200), auth=Depends(authorization)):
        return service.locations(auth, warehouse_id, after, limit)

    @router.get("/stock", response_model=MoveStockPage)
    def stock(warehouse_id: UUID, after: UUID | None = None, limit: int = Query(default=50, ge=1, le=200), auth=Depends(authorization)):
        return service.stock(auth, warehouse_id, after, limit)

    @router.get("/operations/{key}", response_model=OperationView)
    def operation(key: UUID, auth=Depends(authorization)):
        return service.operation(auth, key)

    @router.get("/{doc_id}", response_model=MoveView)
    def read(doc_id: UUID, auth=Depends(authorization)):
        return service.read(auth, doc_id)

    @router.post("", response_model=OrderResult, status_code=201)
    def create(payload: MoveInput, request: Request, access: Annotated[str, Depends(token)],
               key: Annotated[UUID, Header(alias="Idempotency-Key")]):
        result = service.write(access, key, payload, request.state.request_id)
        return JSONResponse(result.body, status_code=result.http_status)

    @router.put("/{doc_id}", response_model=OrderResult)
    def update(doc_id: UUID, payload: MoveUpdate, request: Request, access: Annotated[str, Depends(token)],
               key: Annotated[UUID, Header(alias="Idempotency-Key")]):
        result = service.write(access, key, payload, request.state.request_id, doc_id)
        return JSONResponse(result.body, status_code=result.http_status)

    @router.post("/{doc_id}/post", response_model=MovePostResult)
    def post(doc_id: UUID, payload: MovePost, request: Request, access: Annotated[str, Depends(token)],
             key: Annotated[UUID, Header(alias="Idempotency-Key")]):
        result = service.post(access, key, doc_id, payload, request.state.request_id)
        return JSONResponse(result.body, status_code=result.http_status)

    return router

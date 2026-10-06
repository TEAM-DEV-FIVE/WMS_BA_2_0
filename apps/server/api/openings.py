from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse

from apps.server.api.dependencies import identity_dependencies
from packages.contracts import Error
from packages.contracts.consignments import IncomingOwner
from packages.contracts.master_data import Page
from packages.contracts.openings import (
    OpeningInput,
    OpeningPost,
    OpeningPostResult,
    OpeningUpdate,
    OpeningView,
)
from packages.contracts.orders import OrderPage, OrderResult, OrderStatus
from packages.contracts.receipts import OperationView


def opening_router(service):
    return incoming_router(service, "openings", OpeningInput, OpeningUpdate, OpeningView)


def incoming_router(service, route, input_model, update_model, view_model):
    router = APIRouter(
        prefix="/api/v1",
        tags=[route],
        responses={c: {"model": Error} for c in (401, 403, 404, 409, 422, 503)},
    )
    token, authorization = identity_dependencies(service.identity)

    @router.get("/" + route + "/owners", response_model=Page[IncomingOwner])
    def owners(
        warehouse_id: UUID,
        q: str = Query(default="", max_length=200),
        after: UUID | None = None,
        limit: int = Query(default=100, ge=1, le=200),
        auth=Depends(authorization),
    ):
        return service.ownership_options(auth, warehouse_id, q, after, limit)

    @router.get("/" + route, response_model=OrderPage)
    def listing(
        warehouse_id: UUID,
        status: OrderStatus | None = None,
        after: UUID | None = None,
        limit: int = Query(default=50, ge=1, le=200),
        auth=Depends(authorization),
    ):
        return service.orders.listing(
            auth, service.kind, warehouse_id, status, after, limit, consignment_only=service.consignor_only
        )

    @router.get("/" + route + "/operations/{key}", response_model=OperationView)
    def operation(key: UUID, auth=Depends(authorization)):
        return service.operation(auth, key)

    @router.get("/" + route + "/{document_id}", response_model=view_model)
    def read(document_id: UUID, auth=Depends(authorization)):
        return service.read(auth, document_id)

    @router.post("/" + route, response_model=OrderResult, status_code=201)
    def create(
        payload: input_model,
        request: Request,
        access: Annotated[str, Depends(token)],
        key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ):
        result = service.write(access, key, payload, request.state.request_id)
        return JSONResponse(result.body, status_code=result.http_status)

    @router.put("/" + route + "/{document_id}", response_model=OrderResult)
    def update(
        document_id: UUID,
        payload: update_model,
        request: Request,
        access: Annotated[str, Depends(token)],
        key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ):
        result = service.write(access, key, payload, request.state.request_id, document_id)
        return JSONResponse(result.body, status_code=result.http_status)

    @router.post("/" + route + "/{document_id}/post", response_model=OpeningPostResult)
    def post(
        document_id: UUID,
        payload: OpeningPost,
        request: Request,
        access: Annotated[str, Depends(token)],
        key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ):
        result = service.post(access, key, document_id, payload, request.state.request_id)
        return JSONResponse(result.body, status_code=result.http_status)

    return router

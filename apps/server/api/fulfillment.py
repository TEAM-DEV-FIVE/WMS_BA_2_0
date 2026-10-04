from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse

from apps.server.api.dependencies import identity_dependencies
from packages.contracts import Error
from packages.contracts.fulfillment import (
    FulfillmentAction,
    FulfillmentOperation,
    FulfillmentResult,
    FulfillmentView,
    PackageCreate,
    PickAssign,
    PickConfirm,
    PickCreate,
    PickerPage,
)
from packages.contracts.orders import OrderPage, OrderStatus


def fulfillment_router(service):
    router = APIRouter(prefix="/api/v1/fulfillment", tags=["fulfillment"],
                       responses={c: {"model": Error} for c in (401, 403, 404, 409, 422, 503)})
    token, authorization = identity_dependencies(service.identity)

    @router.get("", response_model=OrderPage)
    def listing(warehouse_id: UUID, status: OrderStatus | None = None, after: UUID | None = None,
                limit: int = Query(default=50, ge=1, le=200), auth=Depends(authorization)):
        return service.orders.listing(auth, "ISSUE", warehouse_id, status, after, limit)

    @router.get("/operations/{key}", response_model=FulfillmentOperation)
    def operation(key: UUID, auth=Depends(authorization)):
        return service.operation(auth, key)

    @router.get("/{document_id}", response_model=FulfillmentView)
    def read(document_id: UUID, auth=Depends(authorization)):
        return service.read(auth, document_id)

    @router.get("/{document_id}/assignees", response_model=PickerPage)
    def assignees(document_id: UUID, after: UUID | None = None, limit: int = Query(default=50, ge=1, le=200),
                  auth=Depends(authorization)):
        return service.assignees(auth, document_id, after, limit)

    def register(kind, action, model, create=False):
        def execute(document_id: UUID, entity_id: UUID, payload: model, request: Request, access: Annotated[str, Depends(token)],
                    key: Annotated[UUID, Header(alias="Idempotency-Key")]):
            result = service.command(access, key, document_id, kind + "." + action, payload, request.state.request_id, entity_id)
            return JSONResponse(result.body, status_code=result.http_status)

        def create_entity(document_id: UUID, payload: model, request: Request, access: Annotated[str, Depends(token)],
                          key: Annotated[UUID, Header(alias="Idempotency-Key")]):
            result = service.command(access, key, document_id, kind + ".create", payload, request.state.request_id)
            return JSONResponse(result.body, status_code=result.http_status)
        path = "/{document_id}/" + ("picks" if kind == "pick" else "packages")
        if not create:
            path += "/{entity_id}/" + action
        router.add_api_route(path, create_entity if create else execute, methods=["POST"], response_model=FulfillmentResult,
                             status_code=201 if create else 200, name="fulfillment_" + kind + "_" + action)

    register("pick", "create", PickCreate, True)
    register("pick", "assign", PickAssign)
    register("pick", "confirm", PickConfirm)
    for action in ("start", "reject", "cancel"):
        register("pick", action, FulfillmentAction)
    register("package", "create", PackageCreate, True)
    for action in ("seal", "cancel"):
        register("package", action, FulfillmentAction)
    return router

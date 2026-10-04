from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse

from apps.server.api.dependencies import identity_dependencies
from packages.contracts import Error, PositiveQuantity
from packages.contracts.issues import (
    IssueInput,
    IssueOperation,
    IssuePost,
    IssuePostResult,
    IssueUpdate,
    IssueView,
    ReleaseInput,
    ReservationPlan,
    ReserveInput,
)
from packages.contracts.orders import OrderAction, OrderPage, OrderResult, OrderStatus


def issue_router(service):
    router = APIRouter(prefix="/api/v1/issues", tags=["issues"],
                       responses={c: {"model": Error} for c in (401, 403, 404, 409, 422, 503)})
    token, authorization = identity_dependencies(service.identity)

    @router.get("", response_model=OrderPage)
    def listing(warehouse_id: UUID, status: OrderStatus | None = None, after: UUID | None = None,
                limit: int = Query(default=50, ge=1, le=200), auth=Depends(authorization)):
        return service.orders.listing(auth, "ISSUE", warehouse_id, status, after, limit)

    @router.get("/operations/{key}", response_model=IssueOperation)
    def operation(key: UUID, auth=Depends(authorization)):
        return service.operation(auth, key)

    @router.get("/{document_id}", response_model=IssueView)
    def read(document_id: UUID, auth=Depends(authorization)):
        return service.read(auth, document_id)

    @router.get("/{document_id}/reservation-plan", response_model=ReservationPlan)
    def plan(document_id: UUID, document_line_id: UUID, quantity_base: PositiveQuantity,
             auth=Depends(authorization)):
        return service.plan(auth, document_id, document_line_id, quantity_base)

    @router.post("", response_model=OrderResult, status_code=201)
    def create(payload: IssueInput, request: Request, access: Annotated[str, Depends(token)],
               key: Annotated[UUID, Header(alias="Idempotency-Key")]):
        result = service.write(access, key, payload, request.state.request_id)
        return JSONResponse(result.body, status_code=result.http_status)

    @router.put("/{document_id}", response_model=OrderResult)
    def update(document_id: UUID, payload: IssueUpdate, request: Request, access: Annotated[str, Depends(token)],
               key: Annotated[UUID, Header(alias="Idempotency-Key")]):
        result = service.write(access, key, payload, request.state.request_id, document_id)
        return JSONResponse(result.body, status_code=result.http_status)

    @router.post("/{document_id}/post", response_model=IssuePostResult)
    def post(document_id: UUID, payload: IssuePost, request: Request, access: Annotated[str, Depends(token)],
             key: Annotated[UUID, Header(alias="Idempotency-Key")]):
        result = service.post(access, key, document_id, payload, request.state.request_id)
        return JSONResponse(result.body, status_code=result.http_status)

    def register(action, model):
        def execute(document_id: UUID, payload: model, request: Request, access: Annotated[str, Depends(token)],
                    key: Annotated[UUID, Header(alias="Idempotency-Key")]):
            result = service.manage(access, key, document_id, payload, request.state.request_id, action)
            return JSONResponse(result.body, status_code=result.http_status)
        router.add_api_route("/{document_id}/reservations/" + action, execute, methods=["POST"],
                             response_model=OrderResult, name="issue_" + action)

    register("reserve", ReserveInput)
    register("release", ReleaseInput)
    register("expire", OrderAction)
    return router

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse

from apps.server.api.dependencies import identity_dependencies
from packages.contracts import Error
from packages.contracts.orders import (
    ApprovalView,
    AssignmentInput,
    DecisionInput,
    OrderAction,
    OrderInput,
    OrderPage,
    OrderResult,
    OrderStatus,
    OrderUpdate,
    OrderView,
)


def order_router(service):
    router = APIRouter(
        prefix="/api/v1",
        tags=["orders"],
        responses={c: {"model": Error} for c in (401, 403, 404, 409, 422, 503)},
    )
    token, authorization = identity_dependencies(service.identity)

    def register(kind, path):
        @router.get(path, response_model=OrderPage, name=f"list_{kind}")
        def listing(
            warehouse_id: UUID,
            status: OrderStatus | None = None,
            after: UUID | None = None,
            limit: int = Query(default=50, ge=1, le=200),
            auth=Depends(authorization),
        ):
            return service.listing(auth, kind, warehouse_id, status, after, limit)

        @router.get(path + "/{document_id}", response_model=OrderView, name=f"read_{kind}")
        def read(document_id: UUID, auth=Depends(authorization)):
            return service.read(auth, document_id, kind)

        @router.post(path, response_model=OrderResult, status_code=201, name=f"create_{kind}")
        def create(
            payload: OrderInput,
            request: Request,
            access: Annotated[str, Depends(token)],
            key: Annotated[UUID, Header(alias="Idempotency-Key")],
        ):
            result = service.write(access, key, kind, "create", payload, request.state.request_id)
            return JSONResponse(result.body, status_code=result.http_status)

        @router.put(path + "/{document_id}", response_model=OrderResult, name=f"update_{kind}")
        def update(
            document_id: UUID,
            payload: OrderUpdate,
            request: Request,
            access: Annotated[str, Depends(token)],
            key: Annotated[UUID, Header(alias="Idempotency-Key")],
        ):
            result = service.write(
                access, key, kind, "update", payload, request.state.request_id, document_id
            )
            return JSONResponse(result.body, status_code=result.http_status)

    register("PO", "/purchase-orders")
    register("SO", "/sales-orders")

    def register_action(action, model=OrderAction):
        def execute(
            document_id: UUID,
            payload: model,
            request: Request,
            access: Annotated[str, Depends(token)],
            key: Annotated[UUID, Header(alias="Idempotency-Key")],
        ):
            result = service.write(access, key, None, action, payload, request.state.request_id, document_id)
            return JSONResponse(result.body, status_code=result.http_status)

        router.add_api_route(
            "/documents/{document_id}/" + ("assignments" if action == "assign" else action),
            execute,
            methods=["POST"],
            response_model=OrderResult,
            name="order_" + action,
        )

    for action in ["submit", "revise", "cancel", "close"]:
        register_action(action)
    register_action("assign", AssignmentInput)

    @router.get("/approval-requests/{request_id}", response_model=ApprovalView)
    def approval(request_id: UUID, auth=Depends(authorization)):
        return service.approval(auth, request_id)

    @router.post("/approval-requests/{approval_id}/decide", response_model=OrderResult)
    def decide(
        approval_id: UUID,
        payload: DecisionInput,
        request: Request,
        access: Annotated[str, Depends(token)],
        key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ):
        result = service.write(access, key, None, "decide", payload, request.state.request_id, approval_id)
        return JSONResponse(result.body, status_code=result.http_status)

    return router

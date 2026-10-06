from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse

from apps.server.api.dependencies import identity_dependencies
from packages.contracts import Error
from packages.contracts.operations import (
    OperationsJobPage,
    OperationsView,
    OutboxEventView,
    OutboxPage,
    OutboxReplay,
)


def operations_router(service):
    router = APIRouter(
        prefix="/api/v1/operations",
        tags=["operations"],
        responses={c: {"model": Error} for c in (401, 403, 404, 409, 422, 503)},
    )
    token, authorization = identity_dependencies(service.identity)

    @router.get("/workers", response_model=OperationsView)
    def snapshot(auth=Depends(authorization)):
        return service.snapshot(auth)

    @router.get("/jobs", response_model=OperationsJobPage)
    def jobs(
        kind: Literal["import", "export", "print"],
        after: UUID | None = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        auth=Depends(authorization),
    ):
        return service.jobs(auth, kind, after, limit)

    @router.get("/outbox", response_model=OutboxPage)
    def events(
        after: UUID | None = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        auth=Depends(authorization),
    ):
        return service.events(auth, after, limit)

    @router.post("/outbox/{event_id}/replay", response_model=OutboxEventView)
    def replay(
        event_id: UUID,
        payload: OutboxReplay,
        request: Request,
        key: Annotated[UUID, Header(alias="Idempotency-Key")],
        access=Depends(token),
    ):
        result = service.replay(access, key, event_id, payload, request.state.request_id)
        return JSONResponse(result.body, status_code=result.http_status)

    return router

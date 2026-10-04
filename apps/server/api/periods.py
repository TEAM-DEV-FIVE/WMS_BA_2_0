from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse

from apps.server.api.dependencies import identity_dependencies
from packages.contracts import Error
from packages.contracts.orders import OrderAction
from packages.contracts.periods import PeriodInput, PeriodPage, PeriodReopen, PeriodResult, PeriodView


def period_router(service):
    router = APIRouter(prefix="/api/v1/periods", tags=["periods"],
                       responses={s: {"model": Error} for s in (401, 403, 404, 409, 422, 503)})
    token, authorization = identity_dependencies(service.identity)

    @router.get("", response_model=PeriodPage)
    def listing(warehouse_id: UUID, after: UUID | None = None, limit: int = Query(50, ge=1, le=200), auth=Depends(authorization)):
        return service.listing(auth, warehouse_id, after, limit)

    @router.get("/operations/{key}", response_model=PeriodResult)
    def operation(key: UUID, auth=Depends(authorization)):
        return service.operation(auth, key)

    @router.get("/{period_id}", response_model=PeriodView)
    def read(period_id: UUID, auth=Depends(authorization)):
        return service.read(auth, period_id)

    @router.post("", response_model=PeriodResult, status_code=201)
    def create(payload: PeriodInput, request: Request, access: Annotated[str, Depends(token)],
               key: Annotated[UUID, Header(alias="Idempotency-Key")]):
        result = service.write(access, key, "create", payload, request.state.request_id)
        return JSONResponse(result.body, status_code=result.http_status)

    def register(action, model):
        def command(period_id: UUID, payload: model, request: Request, access: Annotated[str, Depends(token)],
                    key: Annotated[UUID, Header(alias="Idempotency-Key")]):
            result = service.write(access, key, action, payload, request.state.request_id, period_id)
            return JSONResponse(result.body, status_code=result.http_status)
        command.__name__ = "period_" + action.replace("-", "_")
        router.post("/{period_id}/" + action, response_model=PeriodResult)(command)

    for action, model in [("close", OrderAction), ("confirm-reopen", OrderAction), ("reopen", PeriodReopen)]:
        register(action, model)
    return router

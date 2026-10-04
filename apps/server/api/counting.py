from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse

from apps.server.api.dependencies import identity_dependencies
from packages.contracts import Error
from packages.contracts.counting import (
    CountCatalog,
    CountDecisionInput,
    CountEmptyInput,
    CountExtraInput,
    CountInput,
    CountObservationInput,
    CountPage,
    CountPost,
    CountResult,
    CountReview,
    CountView,
)
from packages.contracts.orders import OrderAction


def counting_router(service):
    router = APIRouter(prefix="/api/v1/counts", tags=["counting"],
                       responses={s: {"model": Error} for s in (401, 403, 404, 409, 422, 503)})
    token, authorization = identity_dependencies(service.identity)

    @router.get("", response_model=CountPage)
    def listing(warehouse_id: UUID, after: UUID | None = None, limit: int = Query(50, ge=1, le=200), auth=Depends(authorization)):
        return service.listing(auth, warehouse_id, after, limit)

    @router.get("/catalog/{resource}", response_model=CountCatalog)
    def catalog(resource: Literal["locations", "users", "products", "owners", "agreements"], warehouse_id: UUID,
                after: UUID | None = None, limit: int = Query(50, ge=1, le=200), q: str = Query("", max_length=100), auth=Depends(authorization)):
        return service.catalog(auth, warehouse_id, resource, after, limit, q)

    @router.get("/operations/{key}", response_model=CountResult)
    def operation(key: UUID, auth=Depends(authorization)):
        return service.operation(auth, key)

    @router.get("/{session_id}", response_model=CountView | CountReview)
    def read(session_id: UUID, auth=Depends(authorization)):
        return service.read(auth, session_id)

    @router.post("", response_model=CountResult, status_code=201)
    def create(payload: CountInput, request: Request, access: Annotated[str, Depends(token)],
               key: Annotated[UUID, Header(alias="Idempotency-Key")]):
        result = service.write(access, key, "create", payload, request.state.request_id)
        return JSONResponse(result.body, status_code=result.http_status)

    def register(action, model):
        def command(session_id: UUID, payload: model, request: Request, access: Annotated[str, Depends(token)],
                    key: Annotated[UUID, Header(alias="Idempotency-Key")]):
            result = service.write(access, key, action, payload, request.state.request_id, session_id)
            return JSONResponse(result.body, status_code=result.http_status)
        command.__name__ = "count_" + action
        router.post("/{session_id}/" + action, response_model=CountResult)(command)

    for action, model in [("freeze", OrderAction), ("cancel", OrderAction), ("submit", OrderAction),
                          ("observe", CountObservationInput), ("extra", CountExtraInput), ("confirm-empty", CountEmptyInput),
                          ("decide", CountDecisionInput), ("post", CountPost)]:
        register(action, model)
    return router

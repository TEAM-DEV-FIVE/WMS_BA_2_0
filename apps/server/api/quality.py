from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse

from apps.server.api.dependencies import identity_dependencies
from packages.contracts import Error
from packages.contracts.quality import QualityHistory, QualityInput, QualityResult, QualitySourcePage


def quality_router(service):
    router = APIRouter(prefix="/api/v1/quality", tags=["quality"],
                       responses={code: {"model": Error} for code in (401, 403, 404, 409, 422, 503)})
    token, authorization = identity_dependencies(service.identity)

    @router.get("/sources", response_model=QualitySourcePage)
    def sources(warehouse_id: UUID, after: UUID | None = None,
                limit: int = Query(default=50, ge=1, le=200), auth=Depends(authorization)):
        return service.listing(auth, warehouse_id, after, limit)

    @router.get("/sources/{source_id}", response_model=QualityHistory)
    def history(source_id: UUID, after: UUID | None = None,
                limit: int = Query(default=50, ge=1, le=200), auth=Depends(authorization)):
        return service.history(auth, source_id, after, limit)

    @router.post("/sources/{source_id}/decide", response_model=QualityResult)
    def decide(source_id: UUID, payload: QualityInput, request: Request,
               access: Annotated[str, Depends(token)], key: Annotated[UUID, Header(alias="Idempotency-Key")]):
        result = service.decide(access, key, source_id, payload, request.state.request_id)
        return JSONResponse(result.body, status_code=result.http_status)

    return router

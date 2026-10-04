import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from apps.server.api.dependencies import identity_dependencies
from apps.server.domain.errors import DomainError
from packages.contracts import Error
from packages.contracts.custom_fields import (
    CustomResult,
    EntityType,
    HistoryPage,
    SchemaView,
    SchemaWrite,
    TargetType,
    ValuesView,
    ValuesWrite,
)


class BoundedMetadataRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def bounded(request):
            if not request.headers.get("Authorization", "").lower().startswith("bearer "):
                raise DomainError("UNAUTHENTICATED", "Cần đăng nhập.")
            if request.method in {"POST", "PUT"}:
                data = bytearray()
                async for chunk in request.stream():
                    if len(data) + len(chunk) > 65536:
                        raise DomainError("FILE_LIMIT", "Dữ liệu trường mở rộng vượt 64 KiB.")
                    data.extend(chunk)
                request._body = bytes(data)
                # Bound nesting before JSON parsing, including chunked requests.
                depth, quoted, escaped = 0, False, False
                for char in data:
                    if quoted:
                        if escaped:
                            escaped = False
                        elif char == 92:
                            escaped = True
                        elif char == 34:
                            quoted = False
                    elif char == 34:
                        quoted = True
                    elif char in (91, 123):
                        depth += 1
                        if depth > 8:
                            raise DomainError("INVALID_CUSTOM_FIELDS", "Dữ liệu lồng quá sâu.")
                    elif char in (93, 125):
                        depth -= 1

                def distinct(pairs):
                    result = {}
                    for key, value in pairs:
                        if key in result:
                            raise ValueError("Duplicate key")
                        result[key] = value
                    return result

                try:
                    parsed = json.loads(data, object_pairs_hook=distinct,
                                        parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Nonfinite")))
                    pending = [parsed]
                    while pending:
                        value = pending.pop()
                        if isinstance(value, dict):
                            pending.extend(value.keys())
                            pending.extend(value.values())
                        elif isinstance(value, list):
                            pending.extend(value)
                        elif isinstance(value, str):
                            value.encode("utf-8")
                            if "\x00" in value:
                                raise ValueError("Null character")
                except (ValueError, RecursionError):
                    raise DomainError("INVALID_CUSTOM_FIELDS", "JSON không hợp lệ hoặc có khóa trùng.") from None
            return await original(request)
        return bounded


def custom_field_router(service):
    router = APIRouter(prefix="/api/v1/custom-fields", tags=["custom-fields"], route_class=BoundedMetadataRoute,
                       responses={code: {"model": Error} for code in (401, 403, 404, 409, 413, 422, 503)})
    token, authorization = identity_dependencies(service.identity)

    @router.get("/schemas/{entity_type}", response_model=SchemaView)
    def read_schema(entity_type: EntityType, auth=Depends(authorization)):
        return service.schema_read(auth, entity_type)

    @router.put("/schemas/{entity_type}", response_model=CustomResult)
    def publish(entity_type: EntityType, payload: SchemaWrite, request: Request,
                access: Annotated[str, Depends(token)], key: Annotated[UUID, Header(alias="Idempotency-Key")]):
        result = service.publish(access, key, entity_type, payload, request.state.request_id)
        return JSONResponse(result.body, status_code=result.http_status)

    @router.get("/{target_type}/{target_id}", response_model=ValuesView)
    def read(target_type: TargetType, target_id: UUID, warehouse_id: UUID | None = None,
             latest: bool = False, auth=Depends(authorization)):
        return service.read(auth, target_type, target_id, warehouse_id, latest)

    @router.get("/{target_type}/{target_id}/history", response_model=HistoryPage)
    def history(target_type: TargetType, target_id: UUID, warehouse_id: UUID | None = None,
                before: int | None = Query(default=None, ge=1), limit: int = Query(default=50, ge=1, le=200),
                auth=Depends(authorization)):
        return service.history(auth, target_type, target_id, warehouse_id, before, limit)

    @router.post("/{target_type}/{target_id}/preview", response_model=ValuesView)
    def preview(target_type: TargetType, target_id: UUID, payload: ValuesWrite,
                key: Annotated[UUID, Header(alias="Idempotency-Key")],
                warehouse_id: UUID | None = None, auth=Depends(authorization)):
        return service.preview(auth, target_type, target_id, payload, warehouse_id)

    @router.put("/{target_type}/{target_id}", response_model=CustomResult)
    def update(target_type: TargetType, target_id: UUID, payload: ValuesWrite, request: Request,
               access: Annotated[str, Depends(token)], key: Annotated[UUID, Header(alias="Idempotency-Key")],
               warehouse_id: UUID | None = None):
        result = service.write(access, key, target_type, target_id, payload, request.state.request_id, warehouse_id)
        return JSONResponse(result.body, status_code=result.http_status)

    return router

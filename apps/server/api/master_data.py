from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from apps.server.api.dependencies import identity_dependencies
from apps.server.application.master_data import ENTITIES, MODELS, page
from apps.server.domain.errors import DomainError
from packages.contracts import Error
from packages.contracts.master_data import ConversionCreate, ConversionView, Page, PriceCreate, PriceView


def master_data_router(service):
    router = APIRouter(prefix="/api/v1/master", tags=["master-data"],
                       responses={code: {"model": Error} for code in (401, 403, 404, 409, 422, 503)})
    token, authorization = identity_dependencies(service.identity)

    def register(name):
        create_model, update_model, view_model = MODELS[name]

        def listing(auth=Depends(authorization), limit: int = Query(default=50, ge=1, le=200),
                    after: UUID | None = None, q: str = Query(default="", max_length=160),
                    active: bool | None = None, warehouse_id: UUID | None = None):
            return service.list(auth, name, after=after, q=q, limit=limit, active=active, warehouse_id=warehouse_id)

        def read(entity_id: UUID, auth=Depends(authorization)):
            return service.read(auth, name, entity_id)

        def create(payload: create_model, request: Request, access: Annotated[str, Depends(token)],
                   key: Annotated[UUID, Header(alias="Idempotency-Key")]):
            result = service.write(access, key, name, payload, request.state.request_id)
            return JSONResponse(result.body, status_code=result.http_status)

        def update(entity_id: UUID, payload: update_model, request: Request, access: Annotated[str, Depends(token)],
                   key: Annotated[UUID, Header(alias="Idempotency-Key")]):
            result = service.write(access, key, name, payload, request.state.request_id, entity_id)
            return JSONResponse(result.body, status_code=result.http_status)

        router.add_api_route(f"/{name}", listing, methods=["GET"], response_model=Page[view_model], name=f"list_{name}")
        router.add_api_route(f"/{name}/{{entity_id}}", read, methods=["GET"], response_model=view_model, name=f"read_{name}")
        router.add_api_route(f"/{name}", create, methods=["POST"], response_model=view_model, status_code=201, name=f"create_{name}")
        router.add_api_route(f"/{name}/{{entity_id}}", update, methods=["PUT"], response_model=view_model, name=f"update_{name}")

    for name in ENTITIES:
        register(name)

    @router.get("/product-uoms", response_model=Page[ConversionView])
    def conversions(product_id: UUID, auth=Depends(authorization), after: UUID | None = None,
                    limit: int = Query(default=50, ge=1, le=200), active: bool | None = None):
        auth.require("master.read")
        return page(auth.connection, """SELECT id,product_id,uom_id,factor::text,revision,is_active FROM wms.product_uom
            WHERE product_id=:product AND (CAST(:after AS uuid) IS NULL OR id>:after)
              AND (CAST(:active AS boolean) IS NULL OR is_active=:active) ORDER BY id LIMIT :limit""",
                    {"product": product_id, "after": after, "active": active}, limit)

    @router.post("/product-uoms", response_model=ConversionView, status_code=201)
    def create_conversion(payload: ConversionCreate, request: Request, access: Annotated[str, Depends(token)],
                          key: Annotated[UUID, Header(alias="Idempotency-Key")]):
        result = service.conversion(access, key, payload, request.state.request_id)
        return JSONResponse(result.body, status_code=result.http_status)

    @router.get("/products/{product_id}/prices", response_model=Page[PriceView])
    def prices(product_id: UUID, warehouse_id: UUID, auth=Depends(authorization), after: UUID | None = None,
               limit: int = Query(default=50, ge=1, le=200)):
        auth.require("master.read")
        auth.require("price.read", warehouse_id)
        if not auth.connection.execute(text("SELECT id FROM wms.warehouse WHERE id=:id AND is_active"), {"id": warehouse_id}).first():
            raise DomainError("NOT_FOUND", "Không tìm thấy kho.")
        service.read(auth, "products", product_id)
        return page(auth.connection, """SELECT id,product_id,effective_on,amount::text,currency,source FROM wms.reference_price
            WHERE product_id=:product AND (CAST(:after AS uuid) IS NULL OR id>:after) ORDER BY id LIMIT :limit""",
                    {"product": product_id, "after": after}, limit)

    @router.post("/products/{product_id}/prices", status_code=201)
    def create_price(product_id: UUID, payload: PriceCreate, request: Request, access: Annotated[str, Depends(token)],
                     key: Annotated[UUID, Header(alias="Idempotency-Key")]):
        result = service.price(access, key, product_id, payload, request.state.request_id)
        return JSONResponse(result.body, status_code=result.http_status)

    @router.get("/scan")
    def scan(code: str = Query(min_length=1, max_length=160), auth=Depends(authorization)):
        auth.require("master.read")
        result = auth.connection.execute(text("""SELECT b.id AS barcode_id,b.code,pu.id AS product_uom_id,
            p.id AS product_id,p.sku,p.name,p.tracking,p.expiry_required,pu.uom_id,pu.factor::text,pu.revision,
            p.version AS product_version FROM wms.barcode b
            JOIN wms.product_uom pu ON pu.id=b.product_uom_id AND pu.is_active
            JOIN wms.product p ON p.id=pu.product_id AND p.is_active
            JOIN wms.uom u ON u.id=pu.uom_id AND u.is_active
            WHERE b.code=:code AND b.is_active"""), {"code": code.strip()}).mappings().one_or_none()
        if not result:
            raise DomainError("NOT_FOUND", "Barcode không còn hoạt động hoặc không tồn tại.")
        return dict(result)

    return router

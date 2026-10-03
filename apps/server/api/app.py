import logging
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException

from apps.server.api.identity import identity_router
from apps.server.api.master_data import master_data_router
from apps.server.api.openings import opening_router
from apps.server.api.orders import order_router
from apps.server.api.receipts import receipt_router
from apps.server.api.traceability import traceability_router
from apps.server.application.identity import IdentityService
from apps.server.application.master_data import MasterDataService
from apps.server.application.openings import OpeningService
from apps.server.application.orders import OrderService
from apps.server.application.receipts import ReceiptService
from apps.server.application.traceability import TraceabilityService
from apps.server.domain.errors import DomainError
from apps.server.infrastructure.config import Settings
from apps.server.infrastructure.database import make_engine
from apps.server.infrastructure.migrations import is_ready
from packages.contracts import Error, FieldError, Health

logger = logging.getLogger("wms.api")


def create_app(settings: Settings | None = None, *, engine: Engine | None = None) -> FastAPI:
    settings = settings or Settings()
    owned_engine = engine is None
    database = engine if engine is not None else make_engine(settings)

    @asynccontextmanager
    async def lifespan(app):
        yield
        if owned_engine:
            database.dispose()

    app = FastAPI(title="WMS runtime API", version="0.1.0", lifespan=lifespan,
                  docs_url="/api/v1/docs", openapi_url="/api/v1/openapi.json", redoc_url=None)
    app.state.database = database
    app.state.identity = IdentityService(database, settings)
    app.include_router(identity_router(app.state.identity))
    app.state.master_data = MasterDataService(app.state.identity)
    app.include_router(master_data_router(app.state.master_data))
    app.state.traceability = TraceabilityService(app.state.identity)
    app.include_router(traceability_router(app.state.traceability))
    app.state.orders = OrderService(app.state.identity)
    app.include_router(order_router(app.state.orders))
    app.state.receipts = ReceiptService(app.state.orders)
    app.include_router(receipt_router(app.state.receipts))
    app.state.openings = OpeningService(app.state.orders)
    app.include_router(opening_router(app.state.openings))

    def error(request: Request, status: int, code: str, message: str, **kwargs):
        body = Error(code=code, message=message, request_id=request.state.request_id, **kwargs)
        return JSONResponse(status_code=status, content=body.model_dump(mode="json", exclude_none=True))

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        # Generate our own UUID: do not trust or log arbitrary client header values.
        request.state.request_id = UUID(str(uuid4()))
        try:
            response = await call_next(request)
        except Exception:
            logger.error("unhandled_error request_id=%s", request.state.request_id)
            response = error(request, 500, "INTERNAL_ERROR", "Có lỗi máy chủ. Dùng request_id để tra cứu.")
        response.headers["X-Request-ID"] = str(request.state.request_id)
        response.headers["Cache-Control"] = "no-store"
        if response.status_code == 401:
            response.headers["WWW-Authenticate"] = "Bearer"
        if response.status_code == 429:
            response.headers["Retry-After"] = str(settings.auth_lock_seconds)
        logger.info("request method=%s status=%s request_id=%s",
                    request.method, response.status_code, request.state.request_id)
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Pydantic errors contain input values: never return/log them (e.g. passwords).
        fields = [FieldError(field=".".join(map(str, item["loc"])), code=item["type"],
                             message="Giá trị không hợp lệ.") for item in exc.errors()]
        return error(request, 422, "VALIDATION_ERROR", "Dữ liệu không hợp lệ.", field_errors=fields)

    @app.exception_handler(DomainError)
    async def domain_error(request, exc):
        statuses = {"NOT_FOUND": 404, "FORBIDDEN": 403, "UNAUTHENTICATED": 401,
                    "MFA_INVALID": 401, "REFRESH_REPLAY": 401, "MFA_REQUIRED": 403,
                    "RATE_LIMITED": 429, "MFA_UNAVAILABLE": 503, "DATABASE_BUSY": 503}
        fields = [FieldError(field=exc.field, code=exc.code, message=exc.message)] if exc.field else []
        return error(request, statuses.get(exc.code, 409), exc.code, exc.message, retryable=exc.retryable,
                     field_errors=fields)

    @app.exception_handler(IntegrityError)
    async def integrity_error(request, exc):
        return error(request, 409, "DATA_CONFLICT", "Dữ liệu trùng hoặc tham chiếu không hợp lệ.")

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return error(request, exc.status_code, "NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR",
                     "Không tìm thấy tài nguyên." if exc.status_code == 404 else "Yêu cầu không được xử lý.")

    @app.get("/api/v1/health", response_model=Health, tags=["operations"])
    def health():
        return Health(status="ok")

    @app.get("/api/v1/ready", response_model=Health, responses={503: {"model": Error}}, tags=["operations"])
    def ready(request: Request):
        try:
            if is_ready(database):
                return Health(status="ready")
        except SQLAlchemyError:
            pass
        return error(request, 503, "DATABASE_NOT_READY", "Cơ sở dữ liệu chưa sẵn sàng. Kiểm tra kết nối và migration.",
                     retryable=True)

    return app

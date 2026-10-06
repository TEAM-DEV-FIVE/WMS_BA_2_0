import ipaddress
import ssl
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from apps.desktop.local_store.device import default_data_directory
from packages.contracts import Error, Health
from packages.contracts.compatibility import compatible
from packages.contracts.recovery import route_policy


def save_local_draft(api, method, path, body, key, warehouse=None):
    """Checkpoint already-entered form data before any online permission preflight.

    This never grants permission or sends a command. IdentityClient raises DRAFT_SAVED.
    Read-only POSTs and non-journal clients retain their existing online path.
    """
    if (getattr(api, "recovery", None) is not None and getattr(api, "draft_only", False)
            and method != "GET" and route_policy(method, path)[0] == "COMMAND"):
        api.command(method, path, body, key, warehouse_id=warehouse)


class DesktopSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WMS_", extra="ignore", hide_input_in_errors=True)

    api_url: str = "http://127.0.0.1:8000/api/v1"
    ca_file: Path | None = None
    http_timeout_seconds: float = Field(default=5, gt=0, le=60)
    local_data_dir: Path = Field(default_factory=default_data_directory)
    # The supported entry point forces this on. False preserves library/test clients.
    require_compatibility: bool = False

    @field_validator("api_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("API URL must have a host and no credentials, query or fragment")
        loopback = parsed.hostname == "localhost"
        try:
            loopback = loopback or ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            pass
        if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
            raise ValueError("LAN connections require HTTPS; HTTP is allowed only on loopback")
        if parsed.path.rstrip("/") != "/api/v1":
            raise ValueError("API URL must end in /api/v1")
        return value.rstrip("/")


class ApiError(Exception):
    def __init__(self, code: str, message: str, request_id: str | None = None, field_errors=None):
        super().__init__(message)
        self.code = code
        self.request_id = request_id
        self.field_errors = field_errors or []


class ApiClient:
    def __init__(self, settings: DesktopSettings, *, transport: httpx.BaseTransport | None = None):
        self.require_compatibility = settings.require_compatibility
        context = ssl.create_default_context(cafile=str(settings.ca_file) if settings.ca_file else None)
        self.client = httpx.Client(
            base_url=settings.api_url + "/", verify=context,
            timeout=httpx.Timeout(settings.http_timeout_seconds), transport=transport,
            follow_redirects=False, trust_env=False,
        )

    def health(self, *, readiness: bool = False) -> Health:
        try:
            response = self.client.get("ready" if readiness else "health")
        except httpx.TimeoutException:
            raise ApiError("TIMEOUT", "Máy chủ phản hồi quá hạn. Bạn có thể kiểm tra lại kết nối.") from None
        except httpx.HTTPError:
            raise ApiError("NETWORK_ERROR", "Không kết nối được máy chủ. Kiểm tra LAN và chứng chỉ TLS.") from None
        if not response.is_success:
            try:
                error = Error.model_validate(response.json())
            except (ValueError, TypeError):
                raise ApiError("INVALID_RESPONSE", "Máy chủ trả lỗi không đúng định dạng.") from None
            raise ApiError(error.code, error.message, str(error.request_id))
        try:
            result = Health.model_validate(response.json())
        except (ValueError, TypeError):
            raise ApiError("INVALID_RESPONSE", "Phản hồi máy chủ không đúng định dạng.") from None
        if self.require_compatibility and not compatible(response.headers):
            raise ApiError("INCOMPATIBLE_SERVER", "Máy chủ chưa tương thích phiên bản phục hồi của client. Cập nhật máy chủ trước; giữ nguyên dữ liệu nháp.")
        return result

    def close(self) -> None:
        self.client.close()

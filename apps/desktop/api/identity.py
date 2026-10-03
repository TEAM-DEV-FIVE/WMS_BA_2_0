import sqlite3
from threading import RLock

import httpx

from apps.desktop.api.client import ApiClient, ApiError
from apps.desktop.local_store.device import device_identity
from packages.contracts import Error
from packages.contracts.identity import (
    CurrentUser,
    Enrollment,
    MfaChallenge,
    RecoveryCodes,
    SessionTokens,
    WarehouseSummary,
)


class IdentityClient(ApiClient):
    """Tokens live in RAM only; a single lock serializes refresh rotation."""

    def __init__(self, settings, *, transport=None):
        super().__init__(settings, transport=transport)
        self.settings = settings
        self.device_id = None
        self._tokens: SessionTokens | None = None
        self._challenge: str | None = None
        self._lock = RLock()
        self.session_generation = 0

    def _request(self, method, path, *, body=None, authenticated=False, extra_headers=None):
        headers = dict(extra_headers or {})
        if authenticated:
            if not self._tokens:
                raise ApiError("UNAUTHENTICATED", "Hãy đăng nhập lại.")
            headers["Authorization"] = "Bearer " + self._tokens.access_token
        try:
            response = self.client.request(method, path, json=body, headers=headers)
        except httpx.TimeoutException:
            raise ApiError("TIMEOUT", "Yêu cầu quá hạn. Hãy kiểm tra trạng thái trước khi thử lại.") from None
        except httpx.HTTPError:
            raise ApiError("NETWORK_ERROR", "Mất kết nối máy chủ. Kiểm tra LAN/TLS.") from None
        try:
            data = response.json()
        except ValueError:
            raise ApiError("INVALID_RESPONSE", "Phản hồi máy chủ không hợp lệ.") from None
        if not response.is_success:
            try:
                error = Error.model_validate(data)
            except ValueError:
                raise ApiError("INVALID_RESPONSE", "Phản hồi lỗi không hợp lệ.") from None
            raise ApiError(error.code, error.message, str(error.request_id), error.field_errors)
        return data

    def login(self, username, password):
        with self._lock:
            self.clear()
            if self.device_id is None:
                try:
                    self.device_id = str(device_identity(self.settings.local_data_dir))
                except (OSError, ValueError, sqlite3.Error):
                    raise ApiError("LOCAL_STORAGE_ERROR", "Không mở được mã thiết bị. Giữ thư mục dữ liệu WMS và kiểm tra quyền truy cập.") from None
            data = self._request("POST", "auth/login", body={"username": username, "password": password, "device_id": self.device_id})
            if data.get("status") == "MFA_REQUIRED":
                challenge = MfaChallenge.model_validate(data)
                self._challenge = challenge.challenge_token
                return "MFA_REQUIRED"
            self._tokens = SessionTokens.model_validate(data)
            return "AUTHENTICATED"

    def mfa(self, code):
        with self._lock:
            if not self._challenge:
                raise ApiError("UNAUTHENTICATED", "Hãy đăng nhập lại trước khi nhập MFA.")
            self._tokens = SessionTokens.model_validate(self._request("POST", "auth/mfa", body={"challenge_token": self._challenge, "code": code}))
            self._challenge = None
            return "AUTHENTICATED"

    def refresh(self):
        with self._lock:
            if not self._tokens:
                raise ApiError("UNAUTHENTICATED", "Hãy đăng nhập lại.")
            try:
                data = self._request("POST", "auth/refresh", body={"refresh_token": self._tokens.refresh_token, "device_id": self.device_id})
                self._tokens = SessionTokens.model_validate(data)
            except (ApiError, ValueError):
                # A lost refresh response leaves token state uncertain; never retry the old refresh automatically.
                self.clear()
                raise

    def get(self, path):
        with self._lock:
            try:
                return self._request("GET", path, authenticated=True)
            except ApiError as error:
                if error.code != "UNAUTHENTICATED":
                    raise
                self.refresh()
                try:
                    return self._request("GET", path, authenticated=True)
                except ApiError as retry_error:
                    if retry_error.code in {"UNAUTHENTICATED", "REFRESH_REPLAY"}:
                        self.clear()
                    raise

    def me(self):
        return CurrentUser.model_validate(self.get("auth/me"))

    def command(self, method, path, body, key):
        with self._lock:
            # Never refresh/retry a write automatically. The presenter retains its exact key/body.
            return self._request(method, path, body=body, authenticated=True,
                                 extra_headers={"Idempotency-Key": str(key)})

    def in_session(self, generation, action):
        with self._lock:
            if generation != self.session_generation:
                raise ApiError("UNAUTHENTICATED", "Phiên đã thay đổi. Tải lại dữ liệu.")
            return action()

    def warehouses(self):
        return [WarehouseSummary.model_validate(value) for value in self.get("warehouses")]

    def permissions(self, warehouse_id):
        return self.get(f"warehouses/{warehouse_id}/permissions")

    def enroll(self, password):
        with self._lock:
            return Enrollment.model_validate(self._request("POST", "auth/mfa/enroll", body={"password": password}, authenticated=True))

    def confirm_enrollment(self, factor_id, code):
        with self._lock:
            return self._request("POST", "auth/mfa/confirm", body={"factor_id": str(factor_id), "code": code}, authenticated=True)

    def lifecycle(self, action, body):
        paths = {"change_password": "auth/password/change", "reset_password": "auth/password/reset",
                 "reset_mfa": "auth/mfa/reset", "recovery_codes": "auth/mfa/recovery-codes",
                 "recover_mfa": "auth/mfa/recover"}
        with self._lock:
            try:
                if action == "recover_mfa":
                    if not self._challenge:
                        raise ApiError("UNAUTHENTICATED", "Đăng nhập bằng mật khẩu trước khi khôi phục MFA.")
                    body["challenge_token"] = self._challenge
                data = self._request("POST", paths[action], body=body,
                                     authenticated=action not in {"reset_password", "recover_mfa"})
                if action == "recovery_codes":
                    return RecoveryCodes.model_validate(data)
                if data != {"status": "SIGNED_OUT"}:
                    raise ValueError("Unexpected credential status")
                self.clear()
                return "SIGNED_OUT"
            except Exception:
                # No credential write is replayable. Even a lost response to code
                # rotation requires fresh login before an explicit new operation.
                self.clear()
                raise
            finally:
                body.clear()

    def logout(self):
        with self._lock:
            try:
                if self._tokens:
                    self._request("POST", "auth/logout", authenticated=True)
            finally:
                self.clear()

    def clear(self):
        self.session_generation += 1
        self._tokens = None
        self._challenge = None

    def close(self):
        self.clear()
        super().close()

import hmac
import json
import sqlite3
from threading import RLock
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

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
from packages.contracts.recovery import acknowledgement, canonical, request_digest, route_policy


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
        self.recovery = None
        self.recovery_user = None
        self.draft_only = False
        self.resource_warehouses = {}

    def _request(self, method, path, *, body=None, authenticated=False, extra_headers=None,
                 content=None, binary=False, recovery_hash=None):
        headers = dict(extra_headers or {})
        if authenticated:
            if not self._tokens:
                raise ApiError("UNAUTHENTICATED", "Hãy đăng nhập lại.")
            headers["Authorization"] = "Bearer " + self._tokens.access_token
        try:
            response = self.client.request(method, path, json=body, content=content, headers=headers)
        except httpx.TimeoutException:
            raise ApiError("TIMEOUT", "Yêu cầu quá hạn. Hãy kiểm tra trạng thái trước khi thử lại.") from None
        except httpx.HTTPError:
            raise ApiError("NETWORK_ERROR", "Mất kết nối máy chủ. Kiểm tra LAN/TLS.") from None
        if binary and response.is_success:
            return response
        try:
            data = response.json()
        except ValueError:
            raise ApiError("INVALID_RESPONSE", "Phản hồi máy chủ không hợp lệ.") from None
        if not response.is_success:
            try:
                error = Error.model_validate(data)
            except ValueError:
                raise ApiError("INVALID_RESPONSE", "Phản hồi lỗi không hợp lệ.") from None
            failure = ApiError(error.code, error.message, str(error.request_id), error.field_errors)
            failure.confirmed_rejection = bool(recovery_hash and hmac.compare_digest(
                response.headers.get("X-WMS-Rejected", ""), recovery_hash))
            raise failure
        if recovery_hash and (not isinstance(data, dict) or not hmac.compare_digest(
                response.headers.get("X-WMS-ACK", ""), acknowledgement(recovery_hash, data))):
            raise ApiError("INVALID_RESPONSE", "Chưa nhận ACK khớp lệnh đã lưu. Mở Phục hồi lệnh để đối chiếu.")
        return data

    def file_request(self, method, path, *, content=None, headers=None, binary=False):
        """Same TLS/session guard as JSON commands. Never retry uploads implicitly."""
        with self._lock:
            return self._request(method, path, content=content, authenticated=True,
                                 extra_headers=headers, binary=binary)

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
                data = self._request("GET", path, authenticated=True)
                self._remember_scopes(data)
                return data
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
        with self._lock:
            user = CurrentUser.model_validate(self.get("auth/me"))
            self.recovery_user = str(user.id)
            return user

    def enable_recovery(self):
        from apps.desktop.local_store.recovery import RecoveryJournal
        if self.recovery is None:
            self.recovery = RecoveryJournal(self.settings)

    def _remember_scopes(self, data):
        if isinstance(data, dict):
            warehouse = data.get("warehouse_id") or data.get("source_warehouse_id")
            if data.get("id") and warehouse:
                self.resource_warehouses[str(data["id"])] = str(warehouse)
            for value in data.values():
                if isinstance(value, (list, dict)):
                    self._remember_scopes(value)
        elif isinstance(data, list):
            for value in data:
                self._remember_scopes(value)

    def _journal_call(self, action, *args, **kwargs):
        if self.recovery is None or self.recovery_user is None or self.device_id is None:
            raise ApiError("UNAUTHENTICATED", "Đăng nhập và tải lại phiên để mở dữ liệu phục hồi.")
        return self.recovery.call(self.recovery_user, self.device_id, action, *args, **kwargs)

    def _recovery_request(self, method, path, body, key, *, lookup=False):
        # First send and recovery use identical JSON key order/bytes from canonical storage.
        body = json.loads(canonical(body))
        fingerprint = request_digest(method, path, body, key)
        result = self._request(method, path, body=body, authenticated=True, recovery_hash=fingerprint,
                              extra_headers={"Idempotency-Key": str(key),
                                             "X-WMS-Recovery": "lookup-v1" if lookup else "send-v1"})
        self._remember_scopes(result)
        return result

    def recovery_records(self, warehouse=None):
        with self._lock:
            # Only routing metadata leaves the worker. No saved prices/values exposed after revoked grants.
            return [{"key": r["key"], "state": r["state"], "warehouse": r["warehouse_id"],
                     "method": r["envelope"]["method"], "path": r["envelope"]["path"],
                     "updated_at": r["updated_at"]} for r in self._journal_call("command_list", warehouse)]

    def recover(self, key, *, retry=False):
        from apps.desktop.local_store.recovery import recover_command
        with self._lock:
            record = self._journal_call("checked", key)
            if record is None:
                raise ApiError("NOT_FOUND", "Không có lệnh trong phiên này.")
            return recover_command(self, record, retry=retry)

    def discard_draft(self, key):
        with self._lock:
            return self._journal_call("discard_draft", key)

    def recovery_detail(self, key):
        with self._lock:
            record = self._journal_call("checked", key)
            if record is None or record["state"] == "CONFLICT":
                raise ApiError("COMMAND_REJECTED", "Tải lại màn nghiệp vụ và đối chiếu phiên bản hiện tại.")
            # Never reveal stored business values using a cached/revoked grant.
            try:
                self.recover(key)
            except ApiError as error:
                if error.code != "OPERATION_UNCONFIRMED":
                    raise
            record = self._journal_call("checked", key)
            return {"key": record["key"], "editable": record["state"] == "DRAFT", "body": record["envelope"]["body"]}

    def edit_draft(self, key, body):
        with self._lock:
            detail = self.recovery_detail(key)
            if not detail["editable"]:
                raise ApiError("RECOVERY_REQUIRED", "Lệnh đã gửi không được sửa nội dung.")
            from apps.desktop.local_store.store import canonical_payload
            canonical_payload(body)
            record = self._journal_call("checked", key)
            envelope = record["envelope"]
            try:
                self._recovery_request(envelope["method"], envelope["path"], body, key, lookup=True)
            except ApiError as error:
                if error.code != "OPERATION_UNCONFIRMED":
                    raise
            else:
                raise ApiError("RECOVERY_REQUIRED", "Lệnh đã có ACK; không sửa nháp.")
            self._journal_call("edit_draft", key, body)

    def command(self, method, path, body, key, *, warehouse_id=None):
        with self._lock:
            if self.recovery is not None:
                from apps.desktop.local_store.recovery import recover_command, send_command
                try:
                    policy, _ = route_policy(method, path)
                except ValueError:
                    raise ApiError("RECOVERY_UNSUPPORTED", "Thao tác chưa có trong ma trận phục hồi; cần cập nhật ứng dụng.") from None
                if policy == "COMMAND":
                    key = str(UUID(str(key)))
                    existing = self._journal_call("checked", key)
                    warehouse = (body.get("warehouse_id") or body.get("source_warehouse_id")
                                 or parse_qs(urlsplit(path).query).get("warehouse_id", [None])[0])
                    warehouse = warehouse or (warehouse_id if warehouse_id not in {None, "global"} else None)
                    if not warehouse:
                        warehouse = next((self.resource_warehouses[p] for p in path.split("/")
                                          if p in self.resource_warehouses), "GLOBAL")
                    if warehouse == "GLOBAL":
                        warehouse = next((self.resource_warehouses[str(body[p])] for p in
                                          ("source_order_id", "source_id", "document_id", "receipt_move_id", "snapshot_id")
                                          if str(body.get(p)) in self.resource_warehouses), "GLOBAL")
                    # Preserve the original scope even if the current form selection changed.
                    if existing:
                        warehouse = existing["warehouse_id"]
                    record = self._journal_call("prepare_command", method, path, body, key, warehouse,
                                                draft=self.draft_only)
                    if record["state"] == "DRAFT":
                        raise ApiError("DRAFT_SAVED", "Đã lưu nháp cục bộ, chưa gửi máy chủ. Mở Phục hồi lệnh để tra cứu/gửi sau.")
                    if self.draft_only:
                        raise ApiError("RECOVERY_REQUIRED", "Lệnh này đã gửi hoặc đã đóng nội dung; chế độ nháp không gửi lại. Mở Phục hồi lệnh để đối chiếu.")
                    if existing:
                        return recover_command(self, record, retry=True)
                    envelope = record["envelope"]
                    return send_command(self, record["key"], envelope["method"], envelope["path"], envelope["body"])
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
        self.recovery_user = None
        self.resource_warehouses.clear()
        self.draft_only = False
        if self.recovery is not None:
            self.recovery.release()

    def close(self):
        self.clear()
        if self.recovery is not None:
            self.recovery.close()
            self.recovery = None
        super().close()

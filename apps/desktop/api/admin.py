"""IAM uses one-shot writes, not the inventory CommandBus/replay protocol."""

from dataclasses import dataclass
from threading import Event
from urllib.parse import urlencode
from uuid import UUID

from apps.desktop.api.client import ApiError
from packages.contracts.identity import UserSummary

PAGE_SIZE = 100
PERMISSIONS = {"users": "iam.manage", "roles": "role.manage",
               "grants": "role.manage", "grant-requests": "role.manage"}
ACTION_RESOURCE = {"create_user": "users", "set_active": "users", "revoke_sessions": "users",
                   "request_grant": "grant-requests", "approve_grant": "grant-requests",
                   "revoke_grant": "grants"}
UNCERTAIN_CODES = {"TIMEOUT", "NETWORK_ERROR", "INTERNAL_ERROR", "INVALID_RESPONSE"}


def read_rows(resource, data):
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise ValueError("Invalid list")
    if resource != "roles" and len(data) > PAGE_SIZE:
        raise ValueError("Invalid page size")
    if resource == "users":
        rows = [UserSummary.model_validate(item).model_dump(mode="json") for item in data]
        if len({row["id"] for row in rows}) != len(rows):
            raise ValueError("Duplicate user")
        return rows
    fields = {
        "roles": ("code", "name"),
        "grants": ("id", "user_id", "role_code", "scope_kind", "warehouse_id", "valid_from", "valid_until", "revoked_at"),
        "grant-requests": ("id", "user_id", "role_code", "scope_kind", "warehouse_id", "valid_until", "reason", "requested_by", "requested_at"),
    }[resource]
    rows = []
    for item in data:
        row = {field: item[field] for field in fields}
        if resource == "roles":
            if not all(isinstance(value, str) and value for value in row.values()):
                raise ValueError("Invalid role")
        else:
            for field in ("id", "user_id", "warehouse_id", "requested_by"):
                if field in row and (field != "warehouse_id" or row[field] is not None):
                    row[field] = str(UUID(row[field]))
            if row["scope_kind"] not in {"GLOBAL", "WAREHOUSE", "ALL_WAREHOUSES"}:
                raise ValueError("Invalid scope")
            if any(value is not None and not isinstance(value, str) for value in row.values()):
                raise ValueError("Invalid field")
        rows.append(row)
    key = "code" if resource == "roles" else "id"
    if len({row[key] for row in rows}) != len(rows):
        raise ValueError("Duplicate row")
    return rows


@dataclass
class AdminResult:
    data: object = None
    user: object = None
    code: str = ""
    message: str = ""
    uncertain: bool = False
    signed_out: bool = False
    generation: int = 0


class AdminApi:
    def __init__(self, identity):
        self.identity = identity

    def execute(self, generation, cancelled: Event, resource, action, body, record_id, after):
        # Catch errors inside the worker: Future must not keep tracebacks/frames
        # containing a password or HTTP authorization headers alive in the UI queue.
        result = AdminResult(generation=generation)
        sent = False

        def run():
            nonlocal sent
            if cancelled.is_set():
                return
            result.user = self.identity.me()
            if not result.user.mfa_verified:
                raise ApiError("MFA_REQUIRED", "Cần xác thực MFA để quản trị.")
            if PERMISSIONS[resource] not in result.user.global_permissions:
                raise ApiError("FORBIDDEN", "Phiên hiện tại không có quyền quản trị tương ứng.")
            if cancelled.is_set():
                return
            if action == "load":
                path = resource
                if resource != "roles":
                    path += "?" + urlencode({"limit": PAGE_SIZE, **({"after": after} if after else {})})
                result.data = read_rows(resource, self.identity.get(path))
                return
            method, path = {
                "create_user": ("POST", "users"),
                "set_active": ("PATCH", f"users/{record_id}/active"),
                "revoke_sessions": ("POST", f"users/{record_id}/revoke-sessions"),
                "request_grant": ("POST", "grant-requests"),
                "approve_grant": ("POST", f"grant-requests/{record_id}/approve"),
                "revoke_grant": ("POST", f"grants/{record_id}/revoke"),
            }[action]
            sent = True
            # in_session holds IdentityClient's lock; this request has no refresh,
            # automatic retry, idempotency promise or persistent draft.
            result.data = self.identity._request(method, path, body=body, authenticated=True)
            if action in {"create_user", "set_active"}:
                result.data = UserSummary.model_validate(result.data).model_dump(mode="json")
            elif action in {"request_grant", "approve_grant"}:
                result.data = {"id": str(UUID(result.data["id"])), "status": result.data["status"]}
                if result.data["status"] != ("PENDING" if action == "request_grant" else "APPROVED"):
                    raise ValueError("Invalid write status")
            elif result.data != {"status": "REVOKED"}:
                raise ValueError("Invalid revoke status")
            if action == "revoke_sessions" and record_id == str(result.user.id):
                self.identity.clear()
                result.signed_out = True

        def guarded():
            try:
                run()
            except ApiError as error:
                result.data = None
                result.code = error.code
                result.message = str(error)
                if error.field_errors:
                    result.message += " · " + " · ".join(f"{item.field}: {item.message}" for item in error.field_errors)
                if error.request_id:
                    result.message += f" (request: {error.request_id})"
                result.uncertain = sent and error.code in UNCERTAIN_CODES
                if error.code in {"UNAUTHENTICATED", "REFRESH_REPLAY"}:
                    self.identity.clear()
                    result.signed_out = True
            except Exception:
                result.data = None
                result.code = "INVALID_RESPONSE"
                result.message = "Không đọc được phản hồi quản trị. Tải lại để đối chiếu."
                result.uncertain = sent
            finally:
                if self.identity.session_generation != generation:
                    result.signed_out = True
                result.generation = self.identity.session_generation

        try:
            self.identity.in_session(generation, guarded)
        except ApiError:
            # A queued operation must never become an operation of a new user.
            result.code = "STALE_SESSION"
        finally:
            if body is not None:
                body.clear()
        return result

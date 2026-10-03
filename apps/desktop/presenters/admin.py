from concurrent.futures import ThreadPoolExecutor
from queue import Empty, Queue
from threading import Event
from uuid import UUID

from pydantic import ValidationError

from apps.desktop.api.admin import ACTION_RESOURCE, PAGE_SIZE, PERMISSIONS, AdminApi
from packages.contracts.identity import GrantCreate, RevokeInput, UserActivation, UserCreate


class AdminPresenter:
    def __init__(self, view, identity):
        self.view, self.identity = view, identity
        self.api = AdminApi(identity)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wms-admin")
        self.results = Queue()
        self.cancelled = Event()
        self.sequence = 0
        self.generation = identity.session_generation
        self.user = None
        self.pending = None
        self.closed = False
        self.uncertain_resource = None
        self.reloaded = False

    def allowed(self, resource):
        return bool(self.user and self.user.mfa_verified
                    and PERMISSIONS[resource] in self.user.global_permissions)

    def reset(self, user=None):
        self.sequence += 1
        self.cancelled.set()
        self.cancelled = Event()
        if self.pending:
            self.pending.cancel()
        self.pending = None
        self.user = user
        self.generation = self.identity.session_generation
        self.uncertain_resource = None
        self.reloaded = False
        self.view.admin_clear()

    def submit(self, resource, action, body=None, record_id=None, after=None):
        if self.closed or self.pending:
            if body is not None:
                body.clear()
            return False
        if not self.allowed(resource):
            if body is not None:
                body.clear()
            self.view.admin_error("Cần quyền quản trị tương ứng và phiên đã xác thực MFA.")
            return False
        if action != "load" and self.uncertain_resource:
            if body is not None:
                body.clear()
            self.view.admin_error("Yêu cầu trước chưa rõ kết quả. Tải lại và đối chiếu trước khi tạo thao tác mới.")
            return False
        self.view.admin_busy()
        sequence, generation = self.sequence, self.generation
        future = self.executor.submit(self.api.execute, generation, self.cancelled,
                                      resource, action, body, record_id, after)
        self.pending = future
        # Callback captures a Queue, never a Tk view or presenter.
        queue = self.results
        future.add_done_callback(lambda done: queue.put((sequence, resource, action, after, done)))
        return True

    def load(self, resource, after=None):
        return self.submit(resource, "load", after=after)

    def write(self, action, body=None, record_id=None):
        if self.closed or self.pending:
            return False
        payload = dict(body or {})
        try:
            if record_id is not None:
                record_id = str(UUID(str(record_id)))
            if action == "create_user":
                validated = UserCreate.model_validate(payload)
                payload = validated.model_dump(mode="json")
                payload["password"] = validated.password.get_secret_value()
            elif action == "set_active":
                payload = UserActivation.model_validate(payload).model_dump(mode="json")
            elif action in {"revoke_sessions", "revoke_grant"}:
                payload = RevokeInput.model_validate(payload).model_dump(mode="json")
            elif action == "request_grant":
                validated = GrantCreate.model_validate(payload)
                if (validated.scope_kind == "WAREHOUSE") != (validated.warehouse_id is not None):
                    raise ValueError("scope")
                payload = validated.model_dump(mode="json")
            elif action != "approve_grant":
                raise ValueError("action")
            if action in {"set_active", "revoke_sessions", "revoke_grant", "approve_grant"} and not record_id:
                raise ValueError("selection")
        except (ValidationError, ValueError, TypeError):
            payload.clear()
            # ValidationError can include the original secret: never stringify it.
            self.view.admin_error("Kiểm tra dữ liệu: tài khoản 3–100 ký tự, mật khẩu 12–128, tên 1–200; "
                                  "UUID hợp lệ, lý do 3–2000 ký tự, thời hạn ISO có múi giờ và scope/kho khớp nhau.")
            return False
        return self.submit(ACTION_RESOURCE[action], action, payload, record_id)

    def acknowledge(self):
        if not self.pending and self.reloaded:
            self.uncertain_resource = None
            self.reloaded = False
            self.view.admin_error("Đã ghi nhận đối chiếu. Thao tác mới sẽ là một yêu cầu mới; không tự gửi lại yêu cầu cũ.")

    def drain(self):
        if self.closed:
            return
        while True:
            try:
                sequence, resource, action, after, future = self.results.get_nowait()
            except Empty:
                break
            if sequence != self.sequence:
                continue
            self.pending = None
            result = future.result()
            if result.code == "STALE_SESSION" or result.generation != self.identity.session_generation:
                self.reset()
                self.view.admin_signed_out("Phiên đã thay đổi. Tải lại phiên trước khi quản trị.")
                continue
            if result.signed_out:
                self.reset()
                self.view.admin_signed_out(result.message or "Đã thu hồi phiên hiện tại. Hãy đăng nhập lại.")
                continue
            self.user = result.user or self.user
            if result.code:
                if result.uncertain:
                    self.uncertain_resource = resource
                    self.reloaded = False
                if result.code in {"FORBIDDEN", "MFA_REQUIRED"}:
                    self.reset()
                self.view.admin_error(result.message)
            elif action == "load":
                if self.uncertain_resource == resource:
                    self.reloaded = True
                rows = result.data
                next_after = None
                if resource != "roles" and len(rows) == PAGE_SIZE:
                    next_after = rows[-1]["username" if resource == "users" else "id"]
                self.view.admin_loaded(resource, rows, next_after, after)
            else:
                self.view.admin_saved(action, result.data)
        # Other desktop presenters share the identity client. Its invalidation
        # must also remove admin data even when no admin request is running.
        if self.user and self.identity.session_generation != self.generation:
            self.reset()
            self.view.admin_signed_out("Phiên không còn hiệu lực. Hãy đăng nhập lại.")

    def close(self):
        self.closed = True
        self.sequence += 1
        self.cancelled.set()
        self.executor.shutdown(wait=False, cancel_futures=True)

    def finish(self):
        self.executor.shutdown(wait=True)
        self.pending = self.view = self.user = None
        while not self.results.empty():
            self.results.get_nowait()

# apps/desktop/api/client.py
# API client: nơi DUY NHẤT trong app nói chuyện với server.
import time
import uuid
import httpx


class ApiError(Exception):
    """Server từ chối rõ ràng (sai quyền, thiếu tồn, sai version...)."""

    def __init__(self, code, message, status=0):
        Exception.__init__(self, message)
        self.code = code
        self.message = message
        self.status = status


class UnknownResult(Exception):
    """Mất mạng / timeout: KHÔNG biết server đã ghi sổ hay chưa."""


class ApiClient:
    def __init__(self, base_url, use_mock=True):
        self.base_url = base_url
        self.use_mock = use_mock      # True = dùng server giả, chưa cần backend thật
        self.token = None             # token chỉ giữ trong RAM, không lưu file
        self.user_id = "demo-user"
        self.mock_done = {}           # (chỉ cho mock) key -> kết quả đã "ghi sổ"
        self.mock_lose_response = False

        # UI03 - dữ liệu giả để thử đăng nhập và quản trị (chỉ cho mock)
        self.login_fails = 0          # đếm số lần đăng nhập sai liên tiếp
        self.mock_logged_in = None    # người vừa đăng nhập
        self.mock_users = [
            {"username": "admin", "password": "admin123",
             "display_name": "Quản trị kỹ thuật", "roles": ["SYSADMIN"],
             "mfa": True, "is_active": True},
            {"username": "nhan01", "password": "123456",
             "display_name": "Nhân viên nhận", "roles": ["RECEIVER@WH-A"],
             "mfa": False, "is_active": True},
            {"username": "soan01", "password": "123456",
             "display_name": "Nhân viên soạn", "roles": ["PICKER@WH-A"],
             "mfa": False, "is_active": True},
        ]

    def set_token(self, token):
        self.token = token

    # ---------- Gửi lệnh ghi sổ ----------
    def post_command(self, endpoint, payload, key):
        if self.use_mock:
            return self._mock_post(key)
        headers = {
            "Authorization": "Bearer " + str(self.token),
            "Idempotency-Key": key,
        }
        try:
            r = httpx.post(self.base_url + endpoint, json=payload,
                           headers=headers, timeout=10)
        except httpx.TransportError:
            raise UnknownResult("Mất kết nối, chưa biết server đã ghi sổ chưa.")
        return self._read(r)

    # ---------- Tra kết quả theo key ----------
    def get_operation(self, key):
        if self.use_mock:
            time.sleep(1)
            return self.mock_done.get(key)    # None = NOT_FOUND
        headers = {"Authorization": "Bearer " + str(self.token)}
        try:
            r = httpx.get(self.base_url + "/operations/" + key,
                          headers=headers, timeout=10)
        except httpx.TransportError:
            raise UnknownResult("Mất kết nối khi tra kết quả.")
        if r.status_code == 404:
            return None
        return self._read(r)

    # ---------- Đọc phản hồi ----------
    def _read(self, r):
        if r.status_code == 200:
            return r.json()
        if r.status_code in (502, 503, 504):
            raise UnknownResult("Server tạm thời không phục vụ.")
        try:
            body = r.json()
        except ValueError:
            raise ApiError("ERROR", "Server trả dữ liệu lạ", r.status_code)
        raise ApiError(body.get("code", "ERROR"),
                       body.get("message", "Lỗi không rõ"), r.status_code)

    # =================================================================
    # UI03: đăng nhập, MFA, quản trị người dùng.
    # API thật cho các chức năng này CHƯA có trong OpenAPI
    # (BA_COVERAGE: UC01, UC02, UC29 = MISSING) nên hiện chỉ chạy bằng
    # server giả. Khi backend chốt hợp đồng thì thêm nhánh gọi httpx.
    # =================================================================
    def _not_ready(self):
        raise ApiError("NOT_READY",
                       "API thật chưa có. Hãy để use_mock=True.", 0)

    def login(self, username, password):
        if not self.use_mock:
            self._not_ready()
        time.sleep(1)
        if self.login_fails >= 5:
            raise ApiError("RATE_LIMITED",
                           "Thử quá nhiều lần. Vui lòng chờ vài phút rồi thử lại.",
                           429)
        for u in self.mock_users:
            if (u["username"] == username and u["password"] == password
                    and u["is_active"]):
                self.login_fails = 0
                self.mock_logged_in = u
                return {"mfa_required": u["mfa"],
                        "token": "mock-token-" + username,
                        "username": u["username"],
                        "display_name": u["display_name"],
                        "roles": list(u["roles"])}
        # Sai tên, sai mật khẩu hay bị khóa: LUÔN báo giống nhau
        self.login_fails = self.login_fails + 1
        raise ApiError("LOGIN_FAILED",
                       "Tên đăng nhập hoặc mật khẩu không đúng.", 401)

    def verify_mfa(self, code):
        if not self.use_mock:
            self._not_ready()
        time.sleep(1)
        if code != "123456":              # mã MFA giả
            raise ApiError("MFA_FAILED",
                           "Mã xác thực không đúng hoặc đã hết hạn.", 401)
        u = self.mock_logged_in
        return {"mfa_required": False,
                "token": "mock-token-" + u["username"],
                "username": u["username"],
                "display_name": u["display_name"],
                "roles": list(u["roles"])}

    def list_users(self):
        if not self.use_mock:
            self._not_ready()
        time.sleep(1)
        result = []
        for u in self.mock_users:
            result.append({"username": u["username"],
                           "display_name": u["display_name"],
                           "roles": list(u["roles"]),
                           "is_active": u["is_active"]})
        return result

    def set_user_active(self, username, active):
        if not self.use_mock:
            self._not_ready()
        time.sleep(1)
        if username == self.mock_logged_in["username"]:
            raise ApiError("SELF_LOCK",
                           "Không được tự khóa tài khoản của chính mình.", 403)
        for u in self.mock_users:
            if u["username"] == username:
                u["is_active"] = active
        return {"status": "OK", "request_id": str(uuid.uuid4())}

    def add_grant(self, username, role, scope_kind, warehouse_code, reference):
        if not self.use_mock:
            self._not_ready()
        time.sleep(1)
        if username == self.mock_logged_in["username"]:
            raise ApiError("SELF_GRANT",
                           "Không được tự cấp quyền cho chính mình.", 403)
        where = warehouse_code if warehouse_code != "" else scope_kind
        for u in self.mock_users:
            if u["username"] == username:
                u["roles"].append(role + "@" + where)
        return {"id": str(uuid.uuid4()), "status": "GRANTED",
                "request_id": str(uuid.uuid4())}

    # ---------- Server giả để thử giao diện ----------
    def _mock_post(self, key):
        time.sleep(1)                         # giả vờ mạng chậm 1 giây
        if key in self.mock_done:             # cùng key -> trả kết quả cũ
            return self.mock_done[key]
        result = {"id": str(uuid.uuid4()), "status": "POSTED",
                  "request_id": str(uuid.uuid4())}
        self.mock_done[key] = result          # server đã commit
        if self.mock_lose_response:           # nhưng phản hồi bị mất
            self.mock_lose_response = False
            raise UnknownResult("Mất phản hồi sau khi server đã commit.")
        return result

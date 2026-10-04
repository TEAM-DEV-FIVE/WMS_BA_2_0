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
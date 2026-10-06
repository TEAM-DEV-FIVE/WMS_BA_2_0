"""Storage executor plus explicit HTTP recovery; no widgets, spooler or file uploads."""

import hmac
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

from apps.desktop.api.client import ApiError
from apps.desktop.local_store.commands import CommandStore


class RecoveryJournal:
    def __init__(self, settings):
        self.settings = settings
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wms-recovery-store")
        self.store = self.partition = None

    def work(self, user, device, action, args, kwargs):
        partition = (str(UUID(str(user))), str(UUID(str(device))))
        if partition != self.partition:
            self.close_store()
            self.store = CommandStore(self.settings.local_data_dir / "commands", server_id=self.settings.api_url,
                                      user_id=UUID(partition[0]), device_id=UUID(partition[1]))
            self.partition = partition
        return getattr(self.store, action)(*args, **kwargs)

    def call(self, user, device, action, *args, **kwargs):
        try:
            return self.executor.submit(self.work, user, device, action, args, kwargs).result()
        except Exception:
            raise ApiError("LOCAL_STORAGE_ERROR", "Không lưu/đọc được lệnh hoặc còn lệnh chưa rõ kết quả cùng thao tác. Mở Phục hồi lệnh; giữ thư mục dữ liệu và kiểm tra cửa sổ WMS khác.") from None

    def close_store(self):
        if self.store is not None:
            self.store.close()
        self.store = self.partition = None

    def release(self):
        self.executor.submit(self.close_store)

    def close(self):
        self.executor.submit(self.close_store).result()
        self.executor.shutdown(wait=True)


def recover_command(api, record, *, retry=False):
    """Caller holds IdentityClient's session lock. Retry is always an operator action."""
    envelope, key = record["envelope"], record["key"]
    if record["state"] == "SENDING":
        api._journal_call("command_transition", key, "UNKNOWN")
        record["state"] = "UNKNOWN"
    if record["state"] == "CONFLICT":
        raise ApiError("COMMAND_REJECTED", "Lệnh đã bị từ chối. Tải lại chứng từ và kiểm tra thủ công trước khi lập lệnh mới.")
    method, path, body = (envelope[name] for name in ("method", "path", "body"))
    try:
        result = api._recovery_request(method, path, body, key, lookup=True)
    except ApiError as error:
        if error.code != "OPERATION_UNCONFIRMED" or not retry:
            raise
        if record["state"] == "COMMITTED":
            raise ApiError("INVALID_RESPONSE", "ACK đã lưu không còn tra được; giữ hồ sơ để đối chiếu.") from None
        if record["state"] == "DRAFT":
            api._journal_call("command_transition", key, "READY")
        return send_command(api, key, method, path, body)
    if record["state"] == "COMMITTED":
        from packages.contracts.recovery import digest
        if not hmac.compare_digest(digest(record["response"]), digest(result)):
            raise ApiError("INVALID_RESPONSE", "ACK khác bản đã lưu; giữ hồ sơ để đối chiếu.")
        return result
    if record["state"] == "DRAFT":
        api._journal_call("command_transition", key, "READY")
    if record["state"] in {"DRAFT", "READY"}:
        api._journal_call("command_transition", key, "SENDING")
    api._journal_call("command_transition", key, "COMMITTED", result)
    return result


def send_command(api, key, method, path, body):
    api._journal_call("command_transition", key, "SENDING")
    try:
        result = api._recovery_request(method, path, body, key)
    except Exception as error:
        rejected = isinstance(error, ApiError) and getattr(error, "confirmed_rejection", False)
        # Never persist an arbitrary error message/input echoed by another server/proxy.
        response = {"code": "COMMAND_REJECTED"} if rejected else None
        api._journal_call("command_transition", key, "CONFLICT" if rejected else "UNKNOWN", response)
        raise
    api._journal_call("command_transition", key, "COMMITTED", result)
    return result

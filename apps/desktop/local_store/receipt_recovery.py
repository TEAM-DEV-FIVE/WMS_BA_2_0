"""Worker-owned receipt posting journal. No write is automatically sent on startup."""

import json
import re
from uuid import UUID

from apps.desktop.api.client import ApiError
from apps.desktop.local_store.store import LocalStore
from packages.contracts.receipts import OperationView, ReceiptPost, ReceiptPostResult

DEFINITIVE_FAILURES = {
    "INVALID_STATE",
    "STALE_VERSION",
    "STALE_APPROVAL",
    "INVALID_REFERENCE",
    "SOURCE_EXCEEDED",
    "RECEIPT_EXCEEDED",
    "TRACKING_MISMATCH",
    "DUPLICATE_SERIAL",
    "LOT_EXPIRY_REQUIRED",
    "LOT_METADATA_CONFLICT",
    "LOT_EXPIRED",
    "SERIAL_ALREADY_PRESENT",
    "PERIOD_CLOSED",
    "LOCATION_FROZEN",
    "DATA_CONFLICT",
    "VALIDATION_ERROR",
    "SOURCE_MISMATCH",
    "OWNERSHIP_UNRESOLVED",
    "UNSUPPORTED_RECEIPT",
    "INVALID_AGREEMENT",
}


def receipt_endpoint(endpoint):
    match = re.fullmatch(r"/?receipts/([0-9a-fA-F-]{36})/post", endpoint)
    if not match:
        raise ValueError("Unsupported local operation endpoint")
    doc_id = UUID(match[1])
    return doc_id, f"receipts/{doc_id}/post"


class ReceiptPostJournal:
    def __init__(self, directory, server_id):
        self.directory, self.server_id = directory, server_id
        self.store = None
        self.partition = None

    def open(self, user_id, device_id):
        partition = (UUID(str(user_id)), UUID(str(device_id)))
        if self.partition != partition:
            self.close()
            self.store = LocalStore(
                self.directory / "receipts",
                server_id=self.server_id,
                user_id=partition[0],
                device_id=partition[1],
            )
            self.partition = partition

    def close(self):
        try:
            if self.store:
                self.store.close()
        finally:
            self.store = self.partition = None

    def snapshot(self):
        records = self.store.operations()
        # Context is display-only; corrupt JSON must block operation recovery rather than be erased.
        result = []
        for record in records:
            _, payload, doc_id, _ = self.checked(UUID(record["key"]))
            context = json.loads(record["context"])
            response = json.loads(record["response"]) if record["response"] else None
            if not isinstance(context, dict) or not isinstance(context.get("document_number", ""), str):
                raise ValueError("Invalid local display context")
            if response is not None and not isinstance(response, dict):
                raise ValueError("Invalid local acknowledgement")
            if record["state"] == "COMMITTED":
                self.acknowledgement(response, doc_id, payload)
            if record["state"] == "CONFLICT" and (
                not response or not isinstance(response.get("message"), str)
            ):
                raise ValueError("Invalid local rejection")
            result.append({**record, "context": context, "payload": payload, "response": response})
        return result

    def checked(self, key):
        record, body = self.store.verify(key)
        doc_id, endpoint = receipt_endpoint(record["endpoint"])
        payload = ReceiptPost.model_validate(body)
        if payload.execution_key != UUID(record["execution_key"]):
            raise ValueError("Execution key differs from the persisted body")
        return record, body, doc_id, endpoint

    def acknowledgement(self, data, doc_id, body, *, direct=False):
        try:
            if direct:
                result = ReceiptPostResult.model_validate(data)
                if result.kind != "RECEIPT":
                    raise ValueError("Wrong resource kind")
                data = {k: data[k] for k in ["id", "status", "version", "request_id", "transaction_id"]}
            ack = OperationView.model_validate(data)
            if (
                ack.operation_status != "COMMITTED"
                or ack.id != doc_id
                or ack.status not in {"PARTIAL", "COMPLETED"}
                or ack.version != body["expected_version"] + 1
            ):
                raise ValueError("Acknowledgement does not match the saved command")
            return ack.model_dump(mode="json")
        except (KeyError, TypeError, ValueError):
            raise ApiError(
                "INVALID_RESPONSE", "Kết quả máy chủ không khớp lệnh đã lưu; giữ yêu cầu để đối chiếu."
            ) from None

    def confirm(self, key, ack):
        record = self.store.operation(key)
        if record["state"] == "COMMITTED":
            if json.loads(record["response"]) != ack:
                raise ApiError("INVALID_RESPONSE", "Kết quả tra cứu khác xác nhận đã lưu; cần đối chiếu.")
            return
        if record["state"] == "READY":
            self.store.transition(key, "SENDING")
        self.store.transition(key, "COMMITTED", response=ack)

    def send_new(self, api, *, key, endpoint, body, context):
        doc_id, endpoint = receipt_endpoint(endpoint)
        payload = ReceiptPost.model_validate(body)
        if self.store.operations(unresolved_only=True, limit=1):
            raise ApiError(
                "RECOVERY_REQUIRED", "Còn lệnh nhận hàng chưa rõ kết quả; mở tab Phục hồi nhận hàng."
            )
        self.store.prepare(
            key=key, execution_key=payload.execution_key, endpoint=endpoint, payload=body, context=context
        )
        return self.send(api, key)

    def send(self, api, key):
        record, body, doc_id, endpoint = self.checked(key)
        if record["state"] not in {"READY", "UNKNOWN"}:
            raise ValueError("Only ready/unknown operations can be sent")
        self.store.transition(key, "SENDING")  # Must commit to disk before the HTTP write.
        try:
            result = api.command("POST", endpoint, body, UUID(str(key)))
            ack = self.acknowledgement(result, doc_id, body, direct=True)
        except ApiError as error:
            if error.code in DEFINITIVE_FAILURES:
                self.store.transition(
                    key,
                    "CONFLICT",
                    response={"code": error.code, "message": str(error), "request_id": error.request_id},
                )
            else:
                self.store.transition(key, "UNKNOWN")
            raise
        except Exception:
            self.store.transition(key, "UNKNOWN")
            raise
        self.confirm(key, ack)
        return ack

    def lookup(self, api, key):
        record, body, doc_id, _ = self.checked(key)
        if record["state"] == "SENDING":
            self.store.transition(key, "UNKNOWN")
        if record["state"] == "CONFLICT":
            raise ApiError(
                "COMMAND_REJECTED", "Máy chủ đã từ chối lệnh này; tải lại phiếu trước khi tạo yêu cầu mới."
            )
        try:
            result = api.get(f"operations/{UUID(str(key))}")
        except ApiError as error:
            if error.code == "NOT_FOUND":
                # 404 may also hide revoked source/document scope. It is NEVER proof of non-commit.
                raise ApiError(
                    "OPERATION_UNCONFIRMED",
                    "Chưa tra được kết quả. Giữ lệnh cũ; gửi lại đúng lệnh sẽ được máy chủ kiểm tra quyền và chống trùng.",
                    error.request_id,
                ) from None
            raise
        ack = self.acknowledgement(result, doc_id, body)
        self.confirm(key, ack)
        return ack

    def retry(self, api, key):
        try:
            return self.lookup(api, key)
        except ApiError as error:
            if error.code != "OPERATION_UNCONFIRMED":
                raise
        # Called only by the operator's explicit retry action. Always same endpoint/body/keys.
        return self.send(api, key)

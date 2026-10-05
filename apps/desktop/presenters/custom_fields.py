"""Workers carry plain data; uncertain writes retain the exact body and key."""
from urllib.parse import urlencode
from uuid import NAMESPACE_URL, uuid5

from apps.desktop.api.client import ApiError, save_local_draft
from apps.desktop.presenters.moves import MovePresenter
from packages.contracts.custom_fields import CustomResult, HistoryPage, SchemaView, ValuesView

PATHS = {"PO": "purchase-orders", "SO": "sales-orders", "RECEIPT": "receipts", "OPENING": "openings",
         "ISSUE": "issues", "INTERNAL_MOVE": "moves", "TRANSFER": "transfers", "CUSTOMER_RETURN": "customer-returns",
         "SUPPLIER_RETURN": "supplier-returns", "REVERSAL": "reversals", "PRODUCT": "master/products"}


def run_request(api, generation, cancelled, method, path, body, key, warehouse):
    def execute():
        if cancelled.is_set():
            return None, []
        save_local_draft(api, method, path, body, key, warehouse)
        permissions = api.me().global_permissions
        if cancelled.is_set():
            return None, permissions
        data = api.get(path) if method == "GET" else api.command(method, path, body, key)
        parts = path.split("?")[0].split("/")
        if method != "GET":
            data = CustomResult.model_validate(data).model_dump(mode="json", by_alias=True)
            expected = str(uuid5(NAMESPACE_URL, "wms.custom-fields."+parts[2])) if parts[1] == "schemas" else parts[2]
            if data["id"] != expected or data["version"] != body["expected_version"]+1:
                raise ValueError("ACK identity/version mismatch")
            if parts[1] != "schemas" and data["revision_id"] != body["revision_id"]:
                raise ValueError("ACK schema mismatch")
        elif parts[0] == "custom-fields":
            model = SchemaView if parts[1] == "schemas" else HistoryPage if parts[-1] == "history" else ValuesView
            data = model.model_validate(data).model_dump(mode="json", by_alias=True)
            if model is SchemaView and data["entity_type"] != parts[2]:
                raise ValueError("Wrong schema")
            if model is ValuesView and (data["id"] != parts[2] or data["target_type"] != parts[1]
                    or (data["warehouse_id"] and data["warehouse_id"] != warehouse)):
                raise ValueError("Wrong object/scope")
        elif not isinstance(data.get("items"), list):
            raise ValueError("Invalid target page")
        return data, permissions
    try:
        data, permissions = api.in_session(generation, execute)
        return data, permissions, None, api.session_generation
    except ApiError as exc:
        return None, [], (exc.code, str(exc)), api.session_generation
    except Exception:
        return None, [], ("INVALID_RESPONSE", "Chưa xác minh được phản hồi; giữ đúng yêu cầu để gửi lại."), api.session_generation


class CustomFieldPresenter(MovePresenter):
    def reset(self, user_id=None, warehouse_id=None):
        super().reset(user_id, warehouse_id or ("global" if user_id else None))

    def submit(self, action, method, path, body=None, key=None):
        if self.closed or self.pending or not all(self.scope):
            return False
        self.view.workflow_busy()
        future = self.executor.submit(run_request, self.api, self.generation, self.cancelled,
                                      method, path, body, key, self.warehouse_id)
        self.pending = future
        queue, sequence, scope = self.results, self.sequence, self.scope
        future.add_done_callback(lambda done: queue.put((sequence, scope, action, done)))
        return True

    def target_path(self, target_type, target_id):
        path = f"custom-fields/{target_type}/{target_id}"
        return path + ("?"+urlencode({"warehouse_id": self.warehouse_id}) if self.warehouse_id != "global" else "")

    def targets(self, kind, after=None):
        if kind not in PATHS or (kind != "PRODUCT" and self.warehouse_id == "global"):
            self.view.workflow_error("Chọn kho để tải chứng từ. Điều chỉnh transit mở từ mã chứng từ nguồn.")
            return False
        query = {"limit": 50}
        if kind != "PRODUCT":
            query["warehouse_id"] = self.warehouse_id
        if after:
            query["after"] = after
        return self.submit("targets", "GET", PATHS[kind]+"?"+urlencode(query))

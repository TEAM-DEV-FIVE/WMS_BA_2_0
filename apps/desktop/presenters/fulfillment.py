from urllib.parse import urlencode

from apps.desktop.api.client import ApiError
from apps.desktop.presenters.moves import MovePresenter
from packages.contracts.fulfillment import (
    FulfillmentOperation,
    FulfillmentResult,
    FulfillmentView,
    PickerPage,
)
from packages.contracts.orders import OrderPage


def validate_ack(data, path, body, warehouse):
    result = FulfillmentResult.model_validate(data).model_dump(mode="json")
    parts = path.split("/")
    kind = "pick" if parts[2] == "picks" else "package"
    if (result["id"] != parts[1] or result["warehouse_id"] != warehouse or result["kind"] != "ISSUE"
            or result["version"] != body["expected_version"] + 1 or result["entity_kind"] != kind):
        raise ValueError("ACK scope/version mismatch")
    if len(parts) > 3 and (result["entity_id"] != parts[3] or result["entity_version"] != body["entity_version"] + 1):
        raise ValueError("ACK entity mismatch")
    if "assigned_to" in body and result["assigned_to"] != str(body["assigned_to"]):
        raise ValueError("ACK assignee mismatch")
    expected = {"picks": "OPEN", "packages": "DRAFT", "assign": None, "start": "PICKING",
                "confirm": "DONE", "reject": "CANCELLED", "cancel": "CANCELLED", "seal": "PACKED"}[parts[-1]]
    if expected and result["entity_status"] != expected:
        raise ValueError("ACK status mismatch")
    return result


def run_request(api, generation, cancelled, method, path, body, key, warehouse):
    def execute():
        if cancelled.is_set():
            return None, []
        permissions = api.permissions(warehouse)
        if cancelled.is_set():
            return None, permissions
        data = api.get(path) if method == "GET" else api.command(method, path, body, key)
        parts = path.split("?")[0].split("/")
        if method != "GET":
            data = validate_ack(data, path, body, warehouse)
        elif parts[1:2] == ["operations"]:
            operation = FulfillmentOperation.model_validate(data)
            original_path, original_body = body
            original_parts = original_path.split("/")
            expected_command = "fulfillment." + ("pick" if original_parts[2] == "picks" else "package") + "."
            expected_command += original_parts[-1] if len(original_parts) > 3 else "create"
            if operation.command != expected_command:
                raise ValueError("ACK command mismatch")
            data = validate_ack(operation.result, original_path, original_body, warehouse)
        elif parts[-1] == "assignees":
            data = PickerPage.model_validate(data).model_dump(mode="json")
        elif len(parts) == 2:
            data = FulfillmentView.model_validate(data).model_dump(mode="json")
            if data["id"] != parts[1] or data["warehouse_id"] != warehouse:
                raise ValueError("Document scope mismatch")
        else:
            data = OrderPage.model_validate(data).model_dump(mode="json")
            if any(r["warehouse_id"] != warehouse or r["kind"] != "ISSUE" for r in data["items"]):
                raise ValueError("List scope mismatch")
        return data, permissions
    try:
        data, permissions = api.in_session(generation, execute)
        return data, permissions, None, api.session_generation
    except ApiError as exc:
        return None, [], (exc.code, str(exc)), api.session_generation
    except Exception:
        return None, [], ("INVALID_RESPONSE", "Phản hồi không khớp; giữ đúng yêu cầu để tra ACK/gửi lại."), api.session_generation


class FulfillmentPresenter(MovePresenter):
    """Reuse the scoped RAM retry lifecycle, with fulfillment-specific ACK checks."""

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

    def load(self, resource="fulfillment", after=None):
        return super().load(resource, after)

    def read(self, doc_id):
        return self.submit("read", "GET", "fulfillment/" + str(doc_id))

    def assignees(self, doc_id, after=None):
        params = {"limit": 50, **({"after": after} if after else {})}
        return self.submit("assignees", "GET", f"fulfillment/{doc_id}/assignees?" + urlencode(params))

    def operation(self):
        if self.uncertain:
            _, path, body, key = self.uncertain
            return self.submit("operation", "GET", "fulfillment/operations/" + str(key), (path, body))
        return False

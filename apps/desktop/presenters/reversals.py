"""Reversal commands retain immutable payload/key copies until a verified ACK."""
from urllib.parse import urlencode

from apps.desktop.api.client import ApiError, save_local_draft
from apps.desktop.presenters.moves import MovePresenter
from packages.contracts.orders import OrderPage, OrderResult
from packages.contracts.reversals import (
    ReversalOperation,
    ReversalPreview,
    ReversalResult,
    ReversalSourcePage,
    ReversalView,
)


def validate_ack(data, path, payload, warehouse):
    parts = path.split("/")
    model = ReversalResult if parts[0] == "reversals" else OrderResult
    result = model.model_validate(data).model_dump(mode="json")
    if result["kind"] != "REVERSAL" or result["warehouse_id"] != warehouse:
        raise ValueError("ACK kind/scope mismatch")
    if parts[0] in {"reversals", "documents"} and len(parts) > 1 and result["id"] != parts[1]:
        raise ValueError("ACK document mismatch")
    if parts[0] == "approval-requests" and result["approval_request_id"] != parts[1]:
        raise ValueError("ACK approval mismatch")
    if result["version"] != payload.get("expected_version", 0) + 1:
        raise ValueError("ACK version mismatch")
    if "source_transaction_id" in payload and result.get("source_transaction_id") != payload["source_transaction_id"]:
        raise ValueError("ACK source mismatch")
    expected = {"submit": "SUBMITTED", "revise": "DRAFT", "cancel": "CANCELLED", "post": "COMPLETED"}
    if parts[-1] in expected and result["status"] != expected[parts[-1]]:
        raise ValueError("ACK state mismatch")
    if parts[-1] == "post" and not result["transaction_id"]:
        raise ValueError("ACK ledger missing")
    if parts[-1] == "decide" and result["status"] not in ({"APPROVED", "SUBMITTED"} if payload["decision"] == "APPROVE" else {"REJECTED"}):
        raise ValueError("ACK decision mismatch")
    return result


def run_request(api, generation, cancelled, method, path, body, key, warehouse):
    def execute():
        if cancelled.is_set():
            return None, []
        save_local_draft(api, method, path, body, key, warehouse)
        permissions = api.permissions(warehouse)
        if cancelled.is_set():
            return None, permissions
        data = api.get(path) if method == "GET" else api.command(method, path, body, key)
        parts = path.split("?")[0].split("/")
        if method != "GET":
            data = validate_ack(data, path, body, warehouse)
        elif parts[:2] == ["reversals", "operations"]:
            saved = ReversalOperation.model_validate(data).model_dump(mode="json")
            target = body["path"].split("/")
            action = "create" if len(target) == 1 else "update" if body["method"] == "PUT" else target[-1]
            expected_command = ("reversal." if target[0] == "reversals" else "order.None.") + action
            if saved["command"] != expected_command:
                raise ValueError("ACK command mismatch")
            # Generic order ACKs have a narrower contract than the lookup envelope.
            raw = saved["result"] if target[0] == "reversals" else {k: v for k, v in saved["result"].items() if k in OrderResult.model_fields}
            data = validate_ack(raw, body["path"], body["payload"], warehouse)
        elif parts[0] == "transactions":
            data = ReversalPreview.model_validate(data).model_dump(mode="json")
            if data["source"]["id"] != parts[1] or data["source"]["warehouse_id"] != warehouse:
                raise ValueError("Preview scope/source mismatch")
        elif parts == ["reversals", "sources"]:
            data = ReversalSourcePage.model_validate(data).model_dump(mode="json")
            if any(r["warehouse_id"] != warehouse for r in data["items"]):
                raise ValueError("Sources scope mismatch")
        elif len(parts) == 1:
            data = OrderPage.model_validate(data).model_dump(mode="json")
            if any(r["warehouse_id"] != warehouse or r["kind"] != "REVERSAL" for r in data["items"]):
                raise ValueError("Page scope mismatch")
        else:
            data = ReversalView.model_validate(data).model_dump(mode="json")
            if data["id"] != parts[1] or data["warehouse_id"] != warehouse or data["kind"] != "REVERSAL":
                raise ValueError("Read scope mismatch")
        return data, permissions
    try:
        data, permissions = api.in_session(generation, execute)
        return data, permissions, None, api.session_generation
    except ApiError as exc:
        return None, [], (exc.code, str(exc)), api.session_generation
    except Exception:
        return None, [], ("INVALID_RESPONSE", "Chưa xác minh được phản hồi. Giữ yêu cầu để tra ACK/gửi lại."), api.session_generation


class ReversalPresenter(MovePresenter):
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

    def load(self, resource="reversals", after=None):
        return super().load(resource, after)

    def read(self, doc_id):
        return self.submit("read", "GET", "reversals/" + str(doc_id))

    def preview(self, transaction_id, day):
        return self.submit("preview", "GET", f"transactions/{transaction_id}/reversal-preview?" + urlencode({"business_date": day}))

    def operation(self):
        if self.uncertain:
            method, path, payload, key = self.uncertain
            return self.submit("operation", "GET", "reversals/operations/" + str(key),
                {"method": method, "path": path, "payload": payload})
        return False

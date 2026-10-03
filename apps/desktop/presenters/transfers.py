from urllib.parse import urlencode

from apps.desktop.api.client import ApiError
from apps.desktop.presenters.moves import MovePresenter
from packages.contracts.moves import MoveLocationPage, MoveStockPage
from packages.contracts.orders import OrderPage, OrderResult
from packages.contracts.transfers import (
    TransferAssigneePage,
    TransferEvidencePage,
    TransferHistoryPage,
    TransferPostResult,
    TransferResult,
    TransferView,
)

POST_ACTIONS = {"dispatch": "DISPATCH", "receive": "ARRIVE", "loss-post": "ADJUST"}


def run_transfer_request(api, generation, cancelled, method, path, body, key, warehouse):
    def execute():
        if cancelled.is_set():
            return None, []
        permissions = api.permissions(warehouse)
        if cancelled.is_set():
            return None, permissions
        data = api.get(path) if method == "GET" else api.command(method, path, body, key)
        parts = path.split("?")[0].split("/")
        if method != "GET":
            model = (
                TransferPostResult
                if parts[-1] in POST_ACTIONS
                else TransferResult
                if parts[0] == "transfers"
                else OrderResult
            )
            data = model.model_validate(data).model_dump(mode="json")
            if data["kind"] not in {"TRANSFER", "ADJUSTMENT"} or data["version"] < 1:
                raise ValueError("Invalid transfer acknowledgement")
            if (
                len(parts) > 1
                and parts[0] in {"transfers", "documents"}
                and parts[-1] != "adjustments"
                and data["id"] != parts[1]
            ):
                raise ValueError("Wrong document ACK")
            if parts[-1] == "adjustments" and data["source_transfer_id"] != parts[1]:
                raise ValueError("Wrong loss source ACK")
            if parts[-1] in POST_ACTIONS:
                if data["operation"] != POST_ACTIONS[parts[-1]] or warehouse not in {
                    data["warehouse_id"],
                    data["destination_warehouse_id"],
                }:
                    raise ValueError("Wrong operation/scope ACK")
            if path == "transfers" and (data["warehouse_id"], data["destination_warehouse_id"]) != (
                body["warehouse_id"],
                body["destination_warehouse_id"],
            ):
                raise ValueError("Wrong draft scope ACK")
        elif parts[:2] == ["transfers", "operations"]:
            data = TransferPostResult.model_validate(data).model_dump(mode="json")
            if data["id"] != body["document_id"] or data["operation"] != body["operation"]:
                raise ValueError("Wrong operation ACK")
        else:
            model = (
                OrderPage
                if len(parts) == 1
                else MoveStockPage
                if parts[1] == "stock"
                else MoveLocationPage
                if parts[1] == "locations"
                else TransferHistoryPage
                if parts[-1] == "history"
                else TransferView
            )
            if parts[-1] == "discrepancies":
                model = TransferEvidencePage
            if parts[-1] == "adjustments":
                model = OrderPage
            if parts[-1] == "assignees":
                model = TransferAssigneePage
            data = model.model_validate(data).model_dump(mode="json")
        if (method != "GET" and parts[-1] in POST_ACTIONS) or parts[:2] == ["transfers", "operations"]:
            if (data["operation"] == "ADJUST") != (data["kind"] == "ADJUSTMENT"):
                raise ValueError("Wrong posting kind")
            statuses = {"DISPATCH": {"PARTIAL"}, "ARRIVE": {"PARTIAL", "COMPLETED"}, "ADJUST": {"COMPLETED"}}
            if data["status"] not in statuses[data["operation"]] or warehouse not in {
                data["warehouse_id"],
                data["destination_warehouse_id"],
            }:
                raise ValueError("Invalid posting state/scope")
        return data, permissions

    try:
        data, permissions = api.in_session(generation, execute)
        return data, permissions, None, api.session_generation
    except ApiError as exc:
        return None, [], (exc.code, str(exc)), api.session_generation
    except Exception:
        return (
            None,
            [],
            ("INVALID_RESPONSE", "Không xác minh được phản hồi; giữ nguyên yêu cầu để đối chiếu."),
            api.session_generation,
        )


class TransferPresenter(MovePresenter):
    def submit(self, action, method, path, body=None, key=None):
        if self.closed or self.pending or not all(self.scope):
            return False
        self.view.workflow_busy()
        future = self.executor.submit(
            run_transfer_request,
            self.api,
            self.generation,
            self.cancelled,
            method,
            path,
            body,
            key,
            self.warehouse_id,
        )
        self.pending = future
        queue, sequence, scope = self.results, self.sequence, self.scope
        future.add_done_callback(lambda done: queue.put((sequence, scope, action, done)))
        return True

    def load(self, resource="transfers", after=None, warehouse_id=None):
        params = {"warehouse_id": warehouse_id or self.warehouse_id, "limit": 50}
        if after:
            params["after"] = after
        return self.submit(resource, "GET", resource + "?" + urlencode(params))

    def read(self, doc_id):
        return self.submit("read", "GET", "transfers/" + str(doc_id))

    def history(self, doc_id, after=None):
        path = f"transfers/{doc_id}/history?limit=50"
        if after:
            path += "&after=" + str(after)
        return self.submit("history", "GET", path)

    def operation(self):
        if self.uncertain:
            parts = self.uncertain[1].split("/")
            if parts[-1] in POST_ACTIONS:
                return self.submit(
                    "operation",
                    "GET",
                    "transfers/operations/" + str(self.uncertain[3]),
                    {"document_id": parts[1], "operation": POST_ACTIONS[parts[-1]]},
                )
        return False

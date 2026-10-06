"""Main-thread presenter with immutable command copies and actor/warehouse/session fencing."""
from urllib.parse import urlencode

from apps.desktop.api.client import ApiError, save_local_draft
from apps.desktop.presenters.moves import MovePresenter
from packages.contracts.counting import CountCatalog, CountPage, CountResult, CountReview, CountView
from packages.contracts.periods import PeriodPage, PeriodResult, PeriodView


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
        count = parts[0] == "counts"
        if method != "GET" or parts[1:2] == ["operations"]:
            data = (CountResult if count else PeriodResult).model_validate(data).model_dump(mode="json")
            original = body if method != "GET" else body["payload"]
            target_path = parts if method != "GET" else body["path"].split("/")
            if data["warehouse_id"] != warehouse or data["version"] < 1:
                raise ValueError("ACK scope mismatch")
            if len(target_path) > 1 and data["id"] != target_path[1]:
                raise ValueError("ACK target mismatch")
            if target_path[-1] == "post" and (data["status"] != "POSTED" or not data["transaction_id"] or data["execution_key"] != original["execution_key"]):
                raise ValueError("Invalid posting ACK")
            if "expected_version" in original and data["version"] != original["expected_version"] + 1:
                raise ValueError("ACK version mismatch")
        elif len(parts) == 1:
            data = (CountPage if count else PeriodPage).model_validate(data).model_dump(mode="json")
            if any(r["warehouse_id"] != warehouse for r in data["items"]):
                raise ValueError("Page scope mismatch")
        elif parts[1] == "catalog":
            data = CountCatalog.model_validate(data).model_dump(mode="json")
        else:
            model = (CountView if data.get("mode") == "BLIND" else CountReview) if count else PeriodView
            data = model.model_validate(data).model_dump(mode="json")
            if data["warehouse_id"] != warehouse or data["id"] != parts[1]:
                raise ValueError("Read scope mismatch")
        return data, permissions
    try:
        data, permissions = api.in_session(generation, execute)
        return data, permissions, None, api.session_generation
    except ApiError as exc:
        return None, [], (exc.code, str(exc)), api.session_generation
    except Exception:
        return None, [], ("INVALID_RESPONSE", "Không đọc được ACK; giữ nguyên yêu cầu để tra cứu/gửi lại."), api.session_generation


class CountPresenter(MovePresenter):
    route = "counts"

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

    def load(self, resource=None, after=None):
        return super().load(resource or self.route, after)

    def read(self, doc_id):
        return self.submit("read", "GET", self.route + "/" + str(doc_id))

    def catalog(self, resource, after=None, q=""):
        params = {"warehouse_id": self.warehouse_id, "limit": 100, "q": q}
        if after:
            params["after"] = after
        return self.submit("catalog/" + resource, "GET", "counts/catalog/" + resource + "?" + urlencode(params))

    def operation(self):
        if self.uncertain:
            _, path, payload, key = self.uncertain
            return self.submit("operation", "GET", self.route + "/operations/" + str(key), {"path": path, "payload": payload})
        return False

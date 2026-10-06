from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from queue import Empty, Queue
from urllib.parse import urlencode
from uuid import uuid4

from apps.desktop.api.client import ApiError

REFERENCES = {
    "products": {"base_uom_id": "uoms", "category_id": "categories"},
    "categories": {"parent_id": "categories"},
    "locations": {"warehouse_id": "warehouses", "parent_id": "locations"},
    "stock-owners": {"partner_id": "partners"},
    "consignment-agreements": {"owner_id": "stock-owners", "warehouse_id": "warehouses"},
}


class MasterDataPresenter:
    def __init__(self, view, api):
        self.view, self.api = view, api
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wms-master")
        self.results = Queue()
        self.sequence = 0
        self.closed = False
        self.pending = None
        self.uncertain = None

    def submit(self, action, function):
        if self.closed:
            return
        self.sequence += 1
        sequence = self.sequence
        self.view.catalog_busy()
        generation = self.api.session_generation
        self.pending = self.executor.submit(self.api.in_session, generation, function)
        self.pending.add_done_callback(lambda future: self.results.put((sequence, generation, action, future)))

    def load(self, entity, query="", after=None, *, filters=None):
        def run():
            params = {"q": query, "limit": 50, **(filters or {})}
            if after:
                params["after"] = after
            result = self.api.get("master/" + entity + "?" + urlencode(params))
            if entity == "locations":
                ancestors, warehouses = {}, {}
                for row in result["items"]:
                    warehouse = row["warehouse_id"]
                    if warehouse not in warehouses:
                        warehouses[warehouse] = self.api.get("master/warehouses/" + warehouse)
                    parent = row["parent_id"]
                    seen = set()
                    while parent and parent not in ancestors and parent not in seen:
                        seen.add(parent)
                        node = self.api.get("master/locations/" + parent)
                        ancestors[parent] = node
                        parent = node["parent_id"]
                result["ancestors"], result["warehouses"] = ancestors, warehouses
            refs = {}
            for field, resource in REFERENCES.get(entity, {}).items():
                # First page only; each reference has its own search/paging dialog.
                ref_params = {"active": "true", "limit": 50}
                if entity == "locations" and field == "parent_id" and params.get("warehouse_id"):
                    ref_params["warehouse_id"] = params["warehouse_id"]
                refs[field] = self.api.get("master/" + resource + "?" + urlencode(ref_params))
            return result, refs
        self.submit("load", run)

    def reference(self, path, query="", after=None, *, filters=None, searchable=True):
        params = {"limit": 50, **(filters or {})}
        if searchable:
            params["q"] = query
        if after:
            params["after"] = after
        self.submit("reference", lambda: self.api.get(path + "?" + urlencode(params)))

    def load_page(self, path, params):
        self.submit("page", lambda: self.api.get(path + "?" + urlencode(params)))

    def save(self, entity, record_id, body):
        if self.uncertain:
            self.view.catalog_error("Yêu cầu trước chưa rõ kết quả. Dùng nút Gửi lại cùng yêu cầu.", uncertain=True)
            return
        self.uncertain = (entity, record_id, deepcopy(body), uuid4())
        self.retry()

    def retry(self):
        if not self.uncertain:
            return
        entity, record_id, body, key = self.uncertain
        path = "master/" + entity + ("/" + record_id if record_id else "")
        if entity == "prices":
            path = "master/products/" + body["product_id"] + "/prices"
            body = {field: value for field, value in body.items() if field not in {"product_id", "warehouse_id"}}
        self.submit("save", lambda: self.api.command("PUT" if record_id else "POST", path, body, key))

    def reset(self):
        self.sequence += 1
        if self.pending:
            self.pending.cancel()
        self.uncertain = None
        self.view.catalog_clear()

    def drain(self):
        while True:
            try:
                sequence, generation, action, future = self.results.get_nowait()
            except Empty:
                return
            if self.closed or sequence != self.sequence:
                continue
            self.pending = None
            if generation != self.api.session_generation:
                self.view.catalog_clear()
                self.view.catalog_error("Phiên đã thay đổi. Đăng nhập hoặc tải lại phiên trước khi tiếp tục.",
                                        uncertain=bool(self.uncertain))
                continue
            try:
                result = future.result()
            except ApiError as error:
                uncertain = action == "save" and error.code in {"TIMEOUT", "NETWORK_ERROR", "INTERNAL_ERROR", "INVALID_RESPONSE"}
                if action == "save" and not uncertain:
                    self.uncertain = None
                detail = " · ".join(f"{field.field}: {field.message}" for field in error.field_errors)
                message = str(error) + (" · " + detail if detail else "")
                if error.code in {"FORBIDDEN", "UNAUTHENTICATED", "REFRESH_REPLAY"}:
                    self.view.catalog_clear()
                self.view.catalog_error(message, uncertain=uncertain)
            except Exception:
                self.view.catalog_error("Không đọc được phản hồi danh mục. Tải lại trước khi tiếp tục.", uncertain=action == "save")
            else:
                if action == "save":
                    self.uncertain = None
                    self.view.catalog_saved(result)
                elif action == "reference":
                    self.view.catalog_reference_loaded(result)
                elif action == "page":
                    self.view.catalog_loaded(result, {})
                else:
                    self.view.catalog_loaded(*result)

    def close(self):
        self.closed = True
        self.sequence += 1
        self.executor.shutdown(wait=False, cancel_futures=True)

    def finish(self):
        self.executor.shutdown(wait=True)
        self.pending = self.uncertain = self.view = None
        while not self.results.empty():
            self.results.get_nowait()

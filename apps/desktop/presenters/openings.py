"""Main-thread callbacks; immutable retry intent stays partitioned by actor/kho.

B19 owns durable recovery. This presenter retains commands only for this process.
"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal
from queue import Empty, Queue
from uuid import uuid4

from apps.desktop.api.client import ApiError
from apps.desktop.api.openings import OpeningApi
from packages.contracts.openings import OpeningLineInput
from packages.contracts.traceability import COMPANY_OWNER, UNCLASSIFIED_OWNER

UNKNOWN_CODES = {
    "TIMEOUT",
    "NETWORK_ERROR",
    "INTERNAL_ERROR",
    "INVALID_RESPONSE",
    "UNAUTHENTICATED",
    "REFRESH_REPLAY",
    "FORBIDDEN",
}


def validate_lines(lines, products=None, units=None):
    if not 1 <= len(lines) <= 200:
        raise ValueError("Phiếu tồn đầu kỳ cần 1–200 dòng; không chia nhiều phiếu để vượt giới hạn kho.")
    serials = set()
    for index, line in enumerate(lines, 1):
        spec = OpeningLineInput.model_validate(line)
        if spec.owner_id == UNCLASSIFIED_OWNER:
            raise ValueError("Chưa phân loại chủ hàng; cần chứng cứ và đối soát trước.")
        if (spec.owner_id == COMPANY_OWNER) == bool(spec.consignment_id):
            raise ValueError("Chọn hợp đồng cho chủ ký gửi; COMPANY không gắn hợp đồng.")
        product = (products or {}).get(str(spec.product_id))
        if product:
            qty, tracking = Decimal(spec.quantity_base), product["tracking"]
            if (
                (tracking == "NONE" and (spec.lot_code or spec.serial_code))
                or (tracking == "LOT" and (not spec.lot_code or spec.serial_code))
                or (tracking == "SERIAL" and (not spec.serial_code or spec.lot_code or qty != 1))
            ):
                raise ValueError(f"Dòng {index}: lô/serial không đúng SKU; mỗi serial phải có lượng 1.")
            if tracking != "LOT" and (spec.manufactured_on or spec.expires_on):
                raise ValueError(f"Dòng {index}: ngày sản xuất/hạn dùng chỉ áp dụng cho lô.")
            if product.get("expiry_required") and not spec.expires_on:
                raise ValueError(f"Dòng {index}: SKU yêu cầu hạn dùng.")
            unit = (units or {}).get(product["base_uom_id"])
            if unit and qty != qty.quantize(Decimal(1).scaleb(-unit["decimal_places"])):
                raise ValueError(f"Dòng {index}: số lượng không đúng độ chính xác đơn vị cơ sở.")
        if spec.manufactured_on and spec.expires_on and spec.manufactured_on > spec.expires_on:
            raise ValueError(f"Dòng {index}: hạn dùng phải từ ngày sản xuất trở đi.")
        if spec.serial_code:
            identity = (spec.product_id, spec.serial_code)
            if identity in serials:
                raise ValueError(f"Dòng {index}: serial lặp trong phiếu.")
            serials.add(identity)


@dataclass
class OpeningCommand:
    method: str
    path: str
    body: dict
    key: str
    warehouse: str
    doc_id: str | None
    post: bool = False
    checked: bool = False


class OpeningPresenter:
    def __init__(self, view, api, *, consignment=False):
        self.view, self.api = view, api
        self.openings = OpeningApi(api, consignment=consignment)
        self.draft_permission = "receipt.draft" if consignment else "opening.draft"
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wms-openings")
        self.results = Queue()
        self.sequence = 0
        self.closed = False
        self.pending = None
        self.user_id = self.warehouse = None
        self.commands = {}

    @property
    def scope(self):
        return self.user_id, self.warehouse

    @property
    def uncertain(self):
        return self.commands.get(self.scope)

    def reset(self, user_id=None, warehouse=None):
        self.sequence += 1
        if self.pending:
            self.pending.cancel()
        self.pending = None
        self.user_id = str(user_id) if user_id else None
        self.warehouse = str(warehouse) if warehouse else None
        if self.uncertain:
            self.uncertain.checked = False
        self.view.opening_clear()

    def submit(self, action, fn, context=None):
        if self.closed or self.pending is not None or not all(self.scope):
            return False
        self.sequence += 1
        sequence, generation = self.sequence, self.api.session_generation
        self.view.opening_busy()
        self.pending = self.executor.submit(self.api.in_session, generation, fn)
        self.pending.add_done_callback(
            lambda future: self.results.put((sequence, generation, action, context, future))
        )
        return True

    def load(self, status="", after=None):
        warehouse = self.warehouse

        def run():
            permissions = self.api.permissions(warehouse)
            page = self.openings.page(warehouse, status, after)
            refs = self.openings.references(warehouse) if self.draft_permission in permissions else {}
            return page, refs, permissions

        self.submit("load", run)

    def read(self, doc_id, *, stale=False):
        self.submit("stale" if stale else "read", lambda: self.openings.read(doc_id))

    def catalog(self, resource, query="", after=None):
        warehouse = self.warehouse if resource in {"locations", "owners"} else None
        self.submit("catalog", lambda: self.openings.catalog(resource, warehouse, query, after), resource)

    def product(self, product_id):
        self.submit("product", lambda: self.openings.product(product_id))

    def command(self, method, path, body, doc_id=None, *, post=False):
        if self.uncertain or self.pending is not None or not all(self.scope) or self.closed:
            return
        command = OpeningCommand(method, path, deepcopy(body), str(uuid4()), self.warehouse, doc_id, post)
        self.commands[self.scope] = command
        self.submit("command", lambda: self.openings.execute(command), command)

    def lookup(self, key=None):
        command = self.uncertain
        if command:
            command.checked = False
            self.submit("lookup", lambda: self.openings.inspect(command), command)
        elif key:
            warehouse = self.warehouse

            def run():
                ack = self.openings.operation(key)
                if self.openings.read(ack["id"])["warehouse_id"] != warehouse:
                    raise ApiError("FORBIDDEN", "ACK thuộc kho khác. Chọn đúng kho rồi tra lại.")
                return ack

            self.submit("ack", run, key)

    def retry(self):
        command = self.uncertain
        if command and command.checked:
            command.checked = False
            self.submit("command", lambda: self.openings.execute(command), command)

    def drain(self):
        while True:
            try:
                sequence, generation, action, context, future = self.results.get_nowait()
            except Empty:
                return
            if self.closed or sequence != self.sequence:
                continue
            self.pending = None
            if generation != self.api.session_generation:
                self.view.opening_clear()
                self.view.opening_error("Phiên đã thay đổi. Đăng nhập/tải lại để tra trạng thái.")
                continue
            try:
                result = future.result()
            except ApiError as error:
                if action == "lookup" and error.code == "NOT_FOUND":
                    context.checked = True
                    self.view.opening_checked(None)
                    continue
                if action == "command" and error.code not in UNKNOWN_CODES:
                    self.commands.pop(self.scope, None)
                detail = " · ".join(f"{f.field}: {f.message}" for f in error.field_errors)
                if error.code in {"FORBIDDEN", "UNAUTHENTICATED", "REFRESH_REPLAY"}:
                    self.view.opening_clear()
                self.view.opening_error(f"{error.code}: {error}" + (" · " + detail if detail else ""))
                if (
                    action == "command"
                    and error.code in {"STALE_VERSION", "STALE_APPROVAL"}
                    and context.doc_id
                ):
                    self.read(context.doc_id, stale=True)
            except Exception:
                self.view.opening_error(
                    "Không đọc được phản hồi. Giữ yêu cầu và tra trạng thái trước khi thử lại."
                )
            else:
                if action == "command":
                    self.commands.pop(self.scope, None)
                    self.view.opening_saved(result, context.key, context.post)
                elif action == "lookup":
                    if context.post and result:
                        self.commands.pop(self.scope, None)
                        self.view.opening_saved(result, context.key, True)
                    else:
                        context.checked = True
                        self.view.opening_checked(result)
                elif action == "ack":
                    self.view.opening_saved(result, context, True)
                elif action == "load":
                    self.view.opening_loaded(*result)
                elif action in {"read", "stale"}:
                    self.view.opening_read(result, stale=action == "stale")
                elif action == "product":
                    self.view.opening_product(*result)
                else:
                    self.view.opening_catalog(context, result)

    def close(self):
        self.closed = True
        self.sequence += 1
        self.executor.shutdown(wait=False, cancel_futures=True)

    def finish(self):
        self.executor.shutdown(wait=True)
        self.pending = self.view = None
        self.commands.clear()
        while not self.results.empty():
            self.results.get_nowait()

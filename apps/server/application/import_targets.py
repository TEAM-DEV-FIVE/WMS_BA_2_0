"""Compose existing business handlers in the import transaction (also used in rollback-only dry-run).

The outer import command owns retry, idempotency and commit. Child commands still
authorize and execute their real handlers, but cannot commit an independent UoW.
No access/refresh token is needed by the validation worker or stored in a job.
"""

import hashlib
import json
from collections import defaultdict
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4, uuid5
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from apps.server.application.authorization import Authorization
from apps.server.application.import_parser import issue
from apps.server.application.master_data import CATALOG_LOCK, MODELS, MasterDataService, active_reference, one
from apps.server.application.openings import OpeningService
from apps.server.application.orders import OrderService
from apps.server.application.receipts import ReceiptService
from apps.server.domain.errors import DomainError
from packages.contracts.master_data import ConversionCreate, PriceCreate
from packages.contracts.openings import OpeningInput
from packages.contracts.orders import OrderInput
from packages.contracts.receipts import ReceiptLineInput
from packages.contracts.traceability import COMPANY_OWNER

MAPPING_VERSION = "b09.v2"
NAMESPACE = UUID("44809b73-5cf7-4d4c-bc46-cf836a4354cc")
REFERENCE_TABLES = {
    "warehouse",
    "location",
    "uom",
    "product_category",
    "product",
    "product_uom",
    "partner",
    "lot",
    "serial",
    "stock_owner",
    "consignment_agreement",
}


def digest(value):
    return hashlib.sha256(
        json.dumps(value, default=str, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class TransactionIdentity:
    def __init__(self, identity, auth):
        self.identity, self.auth = identity, auth
        self.engine = self
        self.clock, self.settings = identity.clock, identity.settings

    @contextmanager
    def begin(self):
        yield self.auth.connection

    def authorization(self, connection, access):
        if connection is not self.auth.connection:
            raise RuntimeError("Import child command escaped its transaction")
        return Authorization(connection, self.auth.principal, self.clock())


class TransactionCommands:
    def __init__(self, auth):
        self.auth = auth

    def execute(self, *, actor_id, authorize, handle, **kwargs):
        if actor_id != self.auth.principal.user_id:
            raise RuntimeError("Import actor changed")
        uow = SimpleNamespace(connection=self.auth.connection)
        authorize(uow)
        return handle(uow)


class ImportTargets:
    def __init__(self, identity, auth, job, request_id=None):
        self.identity, self.auth, self.job = identity, auth, job
        self.c = auth.connection
        bound = TransactionIdentity(identity, auth)
        self.master, self.orders = MasterDataService(bound), OrderService(bound)
        self.receipts = ReceiptService(self.orders)
        self.openings = OpeningService(self.orders)
        commands = TransactionCommands(auth)
        self.master.bus = self.orders.bus = self.receipts.bus = self.openings.bus = commands
        self.created, self.references, self.seen = set(), {}, set()
        self.request_id = request_id or uuid4()

    def remember(self, table, row):
        if str(row["id"]) not in self.created and str(row.get("product_id")) not in self.created:
            self.references.setdefault(
                (table, str(row["id"])), dict(table=table, id=str(row["id"]), hash=digest(row))
            )
        return row

    def resolve(self, table, value, column="code", *, optional=False):
        if not value and optional:
            return None
        if table not in REFERENCE_TABLES or column not in {"code", "sku"}:
            raise RuntimeError("Unsupported reference")
        row = one(self.c, f"SELECT * FROM wms.{table} WHERE upper({column})=upper(:value)", value=value)
        if not row or row.get("is_active") is False:
            raise DomainError("UNKNOWN_REFERENCE", "Không tìm thấy danh mục đang hoạt động.", field=column)
        return self.remember(table, row)

    def conversion(self, product, unit, revision=None):
        row = one(
            self.c,
            """SELECT * FROM wms.product_uom WHERE product_id=:product AND uom_id=:unit
            AND is_active AND (CAST(:revision AS integer) IS NULL OR revision=:revision)""",
            product=product["id"],
            unit=unit["id"],
            revision=revision,
        )
        if not row:
            raise DomainError("UNKNOWN_REFERENCE", "Không có quy đổi active đúng revision.", field="uom_code")
        return self.remember("product_uom", row)

    def warehouse(self, code):
        row = self.resolve("warehouse", code)
        if row["id"] != self.job["warehouse_id"]:
            raise DomainError(
                "WRONG_WAREHOUSE", "Dữ liệu khác kho đã chọn khi tải tệp.", field="warehouse_code"
            )
        self.auth.require("document.read", row["id"], hidden=True)
        return row

    def check_unique(self, key):
        if key in self.seen:
            raise DomainError("DUPLICATE_KEY", "Mã/dòng/serial bị lặp trong tệp.")
        self.seen.add(key)

    def master_row(self, kind, row):
        reason = self.job["options"]["reason"]
        data = dict(row)
        name = {
            "01_uom": "uoms",
            "02_categories": "categories",
            "03_warehouses": "warehouses",
            "04_locations": "locations",
            "05_products": "products",
            "07_barcodes": "barcodes",
            "08_partners": "partners",
        }.get(kind)
        key_fields = {
            "06_product_uom": ("sku", "uom_code", "revision"),
            "07_barcodes": ("barcode",),
            "09_lots": ("sku", "lot_code"),
            "10_serials": ("sku", "serial_code"),
            "14_prices": ("sku", "effective_on"),
        }.get(kind, ("sku",) if kind == "05_products" else ("code",))
        self.check_unique(
            tuple(
                str(row.get(k)).upper() if k not in {"serial_code", "lot_code", "barcode"} else row.get(k)
                for k in key_fields
            )
        )
        if kind == "02_categories":
            parent = self.resolve("product_category", data.pop("parent_code"), optional=True)
            data["parent_id"] = parent["id"] if parent else None
        elif kind == "04_locations":
            data["warehouse_id"] = self.warehouse(data.pop("warehouse_code"))["id"]
            parent = self.resolve("location", data.pop("parent_code"), optional=True)
            data["parent_id"] = parent["id"] if parent else None
        elif kind == "05_products":
            data["base_uom_id"] = self.resolve("uom", data.pop("base_uom_code"))["id"]
            category = self.resolve("product_category", data.pop("category_code"), optional=True)
            data["category_id"] = category["id"] if category else None
        elif kind == "07_barcodes":
            product = self.resolve("product", data.pop("sku"), "sku")
            unit = self.resolve("uom", data.pop("uom_code"))
            data["product_uom_id"] = self.conversion(product, unit, data.pop("revision"))["id"]
            data["code"] = data.pop("barcode")
        if name:
            result = self.master.write(
                None, uuid4(), name, MODELS[name][0](**data, reason=reason), self.request_id
            )
            self.created.add(result.body["id"])
            return result.body["id"]
        product = self.resolve("product", data["sku"], "sku")
        if kind == "06_product_uom":
            unit = self.resolve("uom", data["uom_code"])
            previous = one(
                self.c,
                "SELECT * FROM wms.product_uom WHERE product_id=:p AND uom_id=:u ORDER BY revision DESC LIMIT 1",
                p=product["id"],
                u=unit["id"],
            )
            if not data["is_active"] or data["revision"] != (previous["revision"] + 1 if previous else 1):
                if (
                    previous
                    and previous["is_active"]
                    and data["is_active"]
                    and previous["revision"] == data["revision"]
                    and previous["factor"] == Decimal(data["factor"])
                ):
                    self.remember("product_uom", previous)
                    return str(previous["id"])
                raise DomainError(
                    "STALE_VERSION", "Import quy đổi cần revision kế tiếp, active; không thay revision cũ."
                )
            result = self.master.conversion(
                None,
                uuid4(),
                ConversionCreate(
                    product_id=product["id"],
                    uom_id=unit["id"],
                    factor=data["factor"],
                    expected_product_version=product["version"],
                    reason=reason,
                ),
                self.request_id,
            )
        elif kind == "14_prices":
            result = self.master.price(
                None,
                uuid4(),
                product["id"],
                PriceCreate(**{k: data[k] for k in ["effective_on", "amount", "currency", "source"]}),
                self.request_id,
            )
        else:
            return self.tracking_catalog(kind, product, data)
        self.created.add(result.body["id"])
        return result.body["id"]

    def tracking_catalog(self, kind, product, data):
        """Master-only creation of tracking identities; never a stock/warranty mutation."""
        self.auth.require("master.write")
        self.c.execute(text("SELECT id FROM wms.product WHERE id=:id FOR UPDATE"), {"id": product["id"]})
        product = active_reference(self.c, "product", product["id"], "sku")
        lot = kind == "09_lots"
        if product["tracking"] != ("LOT" if lot else "SERIAL"):
            raise DomainError("TRACKING_MISMATCH", "Loại theo dõi không khớp SKU.", field="sku")
        table, column = ("lot", "lot_code") if lot else ("serial", "serial_code")
        spec = ReceiptLineInput(
            source_line_id=uuid4(),
            destination_location_id=uuid4(),
            quantity_base="1",
            **{k: v for k, v in data.items() if k != "sku"},
        )
        self.receipts.validate_tracking(product, spec, Decimal(1))
        old = one(
            self.c,
            f"SELECT * FROM wms.{table} WHERE product_id=:p AND code=:code",
            p=product["id"],
            code=data[column],
        )
        if old:
            raise DomainError("DUPLICATE_CODE", "Mã lô/serial đã tồn tại.", field=column)
        target = uuid4()
        if lot:
            self.c.execute(
                text(
                    "INSERT INTO wms.lot(id,product_id,code,manufactured_on,expires_on,version) VALUES (:id,:p,:code,:made,:expiry,1)"
                ),
                dict(
                    id=target,
                    p=product["id"],
                    code=spec.lot_code,
                    made=spec.manufactured_on,
                    expiry=spec.expires_on,
                ),
            )
        else:
            self.c.execute(
                text("INSERT INTO wms.serial(id,product_id,code) VALUES (:id,:p,:code)"),
                dict(id=target, p=product["id"], code=spec.serial_code),
            )
        self.master.effects(
            self.c,
            self.auth.principal.user_id,
            table,
            target,
            dict(id=str(target), product_id=str(product["id"]), code=data[column]),
            None,
            self.job["options"]["reason"],
            self.request_id,
        )
        self.created.add(str(target))
        return str(target)

    def document_group(self, kind, rows):
        first = rows[0]["payload"]
        warehouse = self.warehouse(first["warehouse_code"])
        if len(rows) > 200:
            raise DomainError(
                "DOCUMENT_LIMIT", "Mỗi chứng từ tối đa 200 dòng; không chia OPENING để lách giới hạn."
            )
        source_key = first["batch_code"] if kind == "11_opening" else first["external_number"]
        doc_kind = "OPENING" if kind == "11_opening" else first["kind"]
        if len(source_key) > 240:
            raise DomainError("INVALID_SOURCE", "Mã nguồn dài quá 240 ký tự.")
        self.c.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {
                "key": int.from_bytes(
                    hashlib.sha256(
                        f"import-source:{warehouse['id']}:{doc_kind}:{source_key}".encode()
                    ).digest()[:8],
                    signed=True,
                )
            },
        )
        if one(
            self.c,
            "SELECT document_id FROM wms.import_document_source WHERE warehouse_id=:wh AND kind=:kind AND source_key=:key",
            wh=warehouse["id"],
            kind=doc_kind,
            key=source_key,
        ):
            raise DomainError("DUPLICATE_SOURCE", "Chứng từ nguồn đã nhập; không tạo lại bằng file/key khác.")
        lines = []
        for row in rows:
            data = row["payload"]
            fields = ["warehouse_code", "business_date"] + (
                [] if kind == "11_opening" else ["partner_code", "kind"]
            )
            if any(data[k] != first[k] for k in fields):
                raise DomainError("HEADER_MISMATCH", "Các dòng cùng phiếu phải cùng kho/đối tác/ngày/loại.")
            product = self.resolve("product", data["sku"], "sku")
            if kind == "12_open_orders":
                self.check_unique((doc_kind, source_key, data["line_no"]))
                if data["line_no"] < 1:
                    raise DomainError("INVALID_LINE", "Số dòng phải dương.", field="line_no")
                unit = self.resolve("uom", data["uom_code"])
                conversion = self.conversion(product, unit)
                lines.append(
                    dict(
                        product_id=product["id"],
                        product_uom_id=conversion["id"],
                        quantity=data["remaining_quantity"],
                        owner_id=COMPANY_OWNER,
                    )
                )
            else:
                location = self.resolve("location", data["location_code"])
                if one(
                    self.c,
                    "SELECT id FROM wms.count_location_lock WHERE location_id=:id AND released_at IS NULL",
                    id=location["id"],
                ):
                    raise DomainError("LOCATION_FROZEN", "Vị trí đang khóa kiểm kê.", field="location_code")
                owner = self.resolve("stock_owner", data["owner_code"])
                agreement = self.resolve("consignment_agreement", data["consignment_code"], optional=True)
                if owner["partner_id"]:
                    partner = active_reference(self.c, "partner", owner["partner_id"], "owner_code")
                    self.remember("partner", partner)
                spec = dict(
                    product_id=product["id"],
                    quantity_base=data["quantity_base"],
                    owner_id=owner["id"],
                    consignment_id=agreement["id"] if agreement else None,
                    destination_location_id=location["id"],
                    lot_code=data["lot_code"],
                    serial_code=data["serial_code"],
                )
                if data["lot_code"]:
                    lot = one(
                        self.c,
                        "SELECT * FROM wms.lot WHERE product_id=:p AND code=:code",
                        p=product["id"],
                        code=data["lot_code"],
                    )
                    if not lot:
                        raise DomainError(
                            "UNKNOWN_REFERENCE", "Nhập danh mục lô/ngày trước tồn đầu kỳ.", field="lot_code"
                        )
                    self.remember("lot", lot)
                    spec.update(manufactured_on=lot["manufactured_on"], expires_on=lot["expires_on"])
                    today = (
                        self.identity.clock()
                        .astimezone(ZoneInfo(self.identity.settings.business_timezone))
                        .date()
                    )
                    if lot["expires_on"] and lot["expires_on"] < today and location["kind"] != "QUARANTINE":
                        raise DomainError(
                            "LOT_EXPIRED", "Lô hết hạn chỉ được nhập vào cách ly.", field="lot_code"
                        )
                if data["serial_code"] and one(
                    self.c,
                    """SELECT s.id FROM wms.serial s WHERE s.product_id=:p AND s.code=:code AND
                    (EXISTS(SELECT 1 FROM wms.serial_position p WHERE p.serial_id=s.id) OR EXISTS(
                    SELECT 1 FROM wms.stock_balance b JOIN wms.stock_item i ON i.id=b.stock_item_id WHERE i.serial_id=s.id AND b.on_hand>0))""",
                    p=product["id"],
                    code=data["serial_code"],
                ):
                    raise DomainError("SERIAL_DUPLICATE", "Serial đã có tồn/vị trí.", field="serial_code")
                lines.append(spec)
        reason = self.job["options"]["reason"]
        if kind == "11_opening":
            periods = (
                self.c.execute(
                    text(
                        "SELECT status FROM wms.stock_period WHERE warehouse_id=:wh AND :day BETWEEN starts_on AND ends_on FOR SHARE"
                    ),
                    {"wh": warehouse["id"], "day": date.fromisoformat(first["business_date"])},
                )
                .scalars()
                .all()
            )
            if periods != ["OPEN"]:
                raise DomainError("PERIOD_CLOSED", "Tồn đầu kỳ cần đúng một kỳ OPEN.")
            result = self.openings.write(
                None,
                uuid4(),
                OpeningInput(
                    warehouse_id=warehouse["id"],
                    batch_key=uuid5(NAMESPACE, f"{warehouse['id']}:{source_key}"),
                    business_date=first["business_date"],
                    signed_count_reference=self.job["options"].get("signed_count_reference"),
                    reason=reason,
                    lines=lines,
                ),
                self.request_id,
            )
        else:
            if doc_kind not in {"PO", "SO"}:
                raise DomainError("INVALID_KIND", "Đơn mở chỉ hỗ trợ PO/SO.", field="kind")
            partner = self.resolve("partner", first["partner_code"])
            result = self.orders.write(
                None,
                uuid4(),
                doc_kind,
                "create",
                OrderInput(
                    warehouse_id=warehouse["id"],
                    partner_id=partner["id"],
                    business_date=first["business_date"],
                    reason=reason,
                    lines=lines,
                ),
                self.request_id,
            )
        self.c.execute(
            text(
                "INSERT INTO wms.import_document_source(warehouse_id,kind,source_key,document_id,job_id) VALUES (:wh,:kind,:key,:doc,:job)"
            ),
            dict(
                wh=warehouse["id"], kind=doc_kind, key=source_key, doc=result.body["id"], job=self.job["id"]
            ),
        )
        return result.body["id"]

    def run(self, rows, *, preview):
        self.c.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": CATALOG_LOCK})
        groups = defaultdict(list)
        kind = self.job["kind"]
        for row in rows:
            data = row["payload"]
            key = (
                (data["kind"], data["external_number"])
                if kind == "12_open_orders"
                else ("OPENING",)
                if kind == "11_opening"
                else (row["row_no"],)
            )
            groups[key].append(row)
        errors, targets = [], []
        for group in groups.values():
            if kind == "12_open_orders":
                group = sorted(group, key=lambda r: r["payload"]["line_no"])
            try:
                with self.c.begin_nested():
                    if kind == "11_opening" and len({r["payload"]["batch_code"] for r in group}) != 1:
                        raise DomainError("BATCH_MISMATCH", "Một tệp/kho chỉ có một batch OPENING.")
                    target = (
                        self.document_group(kind, group)
                        if kind in {"11_opening", "12_open_orders"}
                        else self.master_row(kind, group[0]["payload"])
                    )
                targets.extend(dict(row_no=r["row_no"], id=target) for r in group)
            except (DomainError, ValidationError, IntegrityError) as error:
                if isinstance(error, ValidationError):
                    details = [
                        (
                            ".".join(map(str, e["loc"])),
                            "INVALID_TYPE",
                            "Dữ liệu không đúng contract nghiệp vụ.",
                        )
                        for e in error.errors()
                    ]
                elif isinstance(error, DomainError):
                    details = [(error.field or "row", error.code, error.message)]
                else:
                    details = [("row", "DATA_CONFLICT", "Mã trùng hoặc tham chiếu không hợp lệ.")]
                errors.extend(
                    issue(r["row_no"], col, code, message) for r in group for col, code, message in details
                )
                if not preview:
                    raise DomainError(
                        "IMPORT_INVALID", "Dữ liệu đã đổi/không hợp lệ; chạy lại dry-run."
                    ) from None
        return targets, errors, list(self.references.values())


def check_snapshot(connection, snapshots):
    # Catalogue writes use CATALOG_LOCK; inventory rows are revalidated by the business handlers.
    connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": CATALOG_LOCK})
    for item in snapshots:
        if item["table"] not in REFERENCE_TABLES:
            raise DomainError("STALE_DATA", "Snapshot tham chiếu không hợp lệ.")
        row = one(connection, f"SELECT * FROM wms.{item['table']} WHERE id=:id", id=UUID(item["id"]))
        if not row or digest(row) != item["hash"]:
            raise DomainError("STALE_DATA", "Danh mục đã đổi sau dry-run; kiểm tra lại trước commit.")

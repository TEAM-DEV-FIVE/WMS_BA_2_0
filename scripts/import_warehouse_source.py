"""Import the verified Mendeley snapshot through WMS APIs into a fresh dataset DB.
Original files remain immutable. Operational additions are traced in a private manifest.
"""

import csv
import hashlib
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import text

from apps.server.bootstrap_period import provision
from packages.contracts.traceability import COMPANY_OWNER
from scripts.prepare_training_quality import maintenance, seed_quality
from scripts.prepare_training_workflows import seed_workflows

SOURCE_URL = "https://data.mendeley.com/datasets/pf2w725pw3/1"
SOURCE_SHA256 = "0de6901d639cae782e661ee63d479360b6942b31072e53d07bbde8313cbe9880"
PREFIX = "SRC-"
REASON = "Thiết lập dữ liệu kho và chứng từ liên kết"


def rows(folder, name, delimiter=","):
    with (folder / name).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream, delimiter=delimiter))


def read_source(folder):
    products = rows(folder, "Product.csv", ";")
    orders = rows(folder, "Customer_Order.csv", ";")
    locations = rows(folder, "Storage_Location.csv")
    inventory = Counter()
    for row in rows(folder, "Random_Storage.csv"):
        for key, value in row.items():
            if key.startswith("col_") and value:
                reference, quantity = value.split(";")
                amount = Decimal(quantity)
                if not amount.is_finite() or amount < 0:
                    raise ValueError("Invalid source stock quantity")
                inventory[reference] += 0
    references = {p["Reference"] for p in products}
    if len(references) != len(products) or not references:
        raise ValueError("Duplicate or empty source products")
    if set(inventory) - references or {r["Reference"] for r in orders} - references:
        raise ValueError("Unknown source reference")
    groups = defaultdict(list)
    for row in orders:
        if int(row["quantity (units)"]) < 0:
            raise ValueError("Negative source quantity needs explicit handling")
        groups[row["orderNumber"]].append(row)
    for group in groups.values():
        if (
            len({r["codCustomer"].strip() for r in group}) != 1
            or len({r["creationDate"].split()[0] for r in group}) != 1
        ):
            raise ValueError("Order identity/date conflict")
    # Storage cells include fractional values resembling sizes despite README quantity labels.
    # Do not treat those ambiguous values as stock. Derive operational opening stock from demand.
    demand = Counter()
    for row in orders:
        demand[row["Reference"]] += int(row["quantity (units)"])
    return products, locations, demand, groups


def verify_archive(path):
    if hashlib.sha256(path.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("Source checksum mismatch")


def prepare(engine, settings, folder, username="kien", progress=print):
    if not engine.url.database.startswith(("wms_dataset_", "wms_test_")):
        raise ValueError("A fresh isolated dataset/test database is required")
    with engine.connect() as c:
        if (
            c.execute(text("SELECT count(*) FROM wms.product")).scalar_one()
            or c.execute(text("SELECT count(*) FROM wms.document")).scalar_one()
        ):
            raise ValueError("Refusing to replace existing products/documents")
        actor = c.execute(
            text("SELECT id FROM wms.app_user WHERE username=:name AND is_active"), {"name": username}
        ).scalar_one()
    source_products, locations, inventory, groups = read_source(folder)
    products, warehouses, clients = {}, [], {}
    today = date.today()
    manifest = {
        "source": SOURCE_URL,
        "license": "CC BY 4.0",
        "author": "Rodrigo Furlan de Assis",
        "sha256": SOURCE_SHA256,
        "source_products": len(source_products),
        "source_orders": len(groups),
        "source_locations": len(locations),
        "transformations": [
            "Names describe anonymized references; brand and exact model are not supplied",
            "Opening stock is derived from historical demand, divided across three logical warehouses; it is not certified stock. Ambiguous storage-cell secondary values are retained without treating them as quantities",
            "Two additional warehouses, serial-tracked warehouse equipment and operational workflows are constructed",
            "Historical orders are imported as unexecuted drafts; no shipment history is asserted",
            "Source size strings and picking rows remain in original CSV; order quantities aggregate by reference",
        ],
        "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.glob("*.csv")},
    }
    with maintenance(engine, settings, username, workflows=True, warehouse_prefix=PREFIX, bootstrap=True) as (
        request,
        tokens,
        _,
    ):
        loader, reviewer = tokens[:2]

        def get(path):
            return request("GET", path, token=loader)

        def create(path, **body):
            return request("POST", path, dict(reason=REASON, **body), loader, 201)

        def approve(doc):
            sent = request(
                "POST",
                "documents/" + doc["id"] + "/submit",
                dict(expected_version=doc["version"], reason=REASON),
                loader,
            )
            return request(
                "POST",
                "approval-requests/" + sent["approval_request_id"] + "/decide",
                dict(expected_version=sent["version"], decision="APPROVE", reason=REASON),
                reviewer,
            )

        unit = create("master/uoms", code="UNIT", name="Đơn vị", decimal_places=0)
        categories = {
            key: create("master/categories", code="ABC-" + key, name="Nhóm phân loại " + key)["id"]
            for key in sorted({p["ABCCOD"].strip() for p in source_products})
        }
        equipment = create("master/categories", code="EQUIPMENT", name="Thiết bị vận hành kho")
        fields = [
            ("model", "Mã tham chiếu"),
            ("description", "Mô tả sản phẩm"),
            ("specifications", "Phân loại và kích cỡ"),
            ("storage_guide", "Bảo quản"),
            ("inspection_guide", "Kiểm tra hàng"),
            ("sector", "Khu vực"),
        ]
        schema = request(
            "PUT",
            "custom-fields/schemas/PRODUCT",
            dict(
                expected_version=0,
                reason=REASON,
                fields=[dict(code=k, label=v, value_type="TEXT") for k, v in fields],
            ),
            loader,
        )
        sizes = defaultdict(set)
        for group in groups.values():
            for row in group:
                sizes[row["Reference"]].add(row["Size (US)"])
        items = [
            dict(
                reference=p["Reference"],
                name="Giày " + p["Reference"],
                tracking="NONE",
                category=categories[p["ABCCOD"].strip()],
                sector=p["Sector"].strip(),
                abc=p["ABCCOD"].strip(),
            )
            for p in source_products
        ]
        items += [
            dict(
                reference="000-EQUIP-" + str(i),
                name="Thiết bị quét mã kho " + str(i),
                tracking="SERIAL",
                category=equipment["id"],
                sector="OPS",
                abc="",
            )
            for i in range(1, 4)
        ]
        for item in sorted(items, key=lambda p: p["reference"]):
            ref = item["reference"]
            product = create(
                "master/products",
                sku=PREFIX + ref,
                name=item["name"],
                base_uom_id=unit["id"],
                category_id=item["category"],
                tracking=item["tracking"],
            )
            values = dict(
                model=ref,
                description=(
                    "Sản phẩm giày theo mã tham chiếu "
                    + ref
                    + " thuộc khu "
                    + item["sector"]
                    + ". Quản lý số lượng theo đơn vị và phân loại ABC."
                    if item["tracking"] == "NONE"
                    else "Thiết bị phục vụ quét mã trong kho; theo dõi riêng từng số thiết bị."
                ),
                specifications="Phân loại "
                + item["abc"]
                + "; mã cỡ trong nguồn: "
                + ", ".join(sorted(sizes[ref])),
                sector=item["sector"],
                storage_guide="Giữ khô ráo, tránh nắng và nước; sắp xếp theo mã hàng và kích cỡ.",
                inspection_guide="Đối chiếu mã hàng, kích cỡ, số lượng và ngoại quan; cách ly hàng hỏng.",
            )
            request(
                "PUT",
                "custom-fields/products/" + product["id"],
                dict(
                    expected_version=product["version"],
                    expected_revision_id=None,
                    revision_id=schema["revision_id"],
                    reason=REASON,
                    values=values,
                ),
                loader,
            )
            conversion = get("master/product-uoms?product_id=" + product["id"])["items"][0]
            create("master/barcodes", code=PREFIX + ref, product_uom_id=conversion["id"])
            products[ref] = dict(id=product["id"], unit=conversion["id"], tracking=item["tracking"])
        progress(f"Products prepared: {len(products)}", flush=True)
        supplier = create("master/partners", code="SUPPLY", name="Đầu mối cung ứng", is_supplier=True)
        for index, (suffix, name) in enumerate(
            [("QC", "Kho trung tâm"), ("DT", "Kho Đông Thạnh"), ("BD", "Kho Bình Dương")]
        ):
            warehouse = create("master/warehouses", code=PREFIX + suffix, name=name)
            warehouses.append(warehouse)
            group = create(
                "master/locations",
                code=suffix + "-AREA",
                name="Khu lưu trữ",
                warehouse_id=warehouse["id"],
                kind="GROUP",
            )
            rack = create(
                "master/locations",
                code=suffix + "-RACK",
                name="Dãy kệ",
                warehouse_id=warehouse["id"],
                parent_id=group["id"],
                kind="GROUP",
            )
            bins = [
                create(
                    "master/locations",
                    code=suffix + "-BIN-" + str(i),
                    name="Kệ " + str(i),
                    warehouse_id=warehouse["id"],
                    parent_id=rack["id"],
                    kind="STORAGE",
                )["id"]
                for i in range(1, 6)
            ]
            receiving = None
            for kind, label in [
                ("RECEIVING", "Nhận hàng"),
                ("SHIPPING", "Xuất hàng"),
                ("QUARANTINE", "Cách ly"),
            ]:
                loc = create(
                    "master/locations",
                    code=suffix + "-" + kind,
                    name=label,
                    kind=kind,
                    warehouse_id=warehouse["id"],
                )
                if kind == "RECEIVING":
                    receiving = loc["id"]
            if index == 0:
                for loc in locations:
                    create(
                        "master/locations",
                        code=loc["originalLocation"].strip(),
                        name=loc["originalLocation"].strip() + " [" + loc["position"] + "]",
                        warehouse_id=warehouse["id"],
                        parent_id=rack["id"],
                        kind="STORAGE",
                    )
                progress(f"Source locations prepared: {len(locations)}", flush=True)
            provision(engine, warehouse["code"], date(today.year, 1, 1), date(today.year, 12, 31), REASON)
            opening = []
            for number, (ref, p) in enumerate(list(products.items())[:200]):
                quantity = 1 if p["tracking"] == "SERIAL" else max(20, inventory[ref] // 3)
                line = dict(
                    product_id=p["id"],
                    quantity_base=str(quantity),
                    owner_id=str(COMPANY_OWNER),
                    destination_location_id=bins[number % 5],
                )
                if p["tracking"] == "SERIAL":
                    line["serial_code"] = suffix + "-" + ref
                opening.append(line)
            doc = approve(
                create(
                    "openings",
                    warehouse_id=warehouse["id"],
                    batch_key=str(uuid4()),
                    business_date=str(today),
                    signed_count_reference="INIT-" + suffix,
                    lines=opening,
                )
            )
            request(
                "POST",
                "openings/" + doc["id"] + "/post",
                dict(expected_version=doc["version"], execution_key=str(uuid4()), reason=REASON),
                loader,
            )
            remainder = list(products.items())[200:]
            if remainder:
                po = approve(
                    create(
                        "purchase-orders",
                        warehouse_id=warehouse["id"],
                        partner_id=supplier["id"],
                        business_date=str(today),
                        lines=[
                            dict(
                                product_id=p["id"],
                                product_uom_id=p["unit"],
                                quantity=str(max(20, inventory[ref] // 3)),
                                owner_id=str(COMPANY_OWNER),
                            )
                            for ref, p in remainder
                        ],
                    )
                )
                detail = get("purchase-orders/" + po["id"])
                receipt = approve(
                    create(
                        "receipts",
                        source_order_id=po["id"],
                        business_date=str(today),
                        lines=[
                            dict(
                                source_line_id=line["id"],
                                quantity_base=line["base_quantity"],
                                destination_location_id=receiving,
                            )
                            for line in detail["lines"]
                        ],
                    )
                )
                detail = get("receipts/" + receipt["id"])
                request(
                    "POST",
                    "receipts/" + receipt["id"] + "/post",
                    dict(
                        expected_version=receipt["version"],
                        execution_key=str(uuid4()),
                        reason=REASON,
                        lines=[
                            dict(document_line_id=line["id"], quantity_base=line["base_quantity"])
                            for line in detail["lines"]
                        ],
                    ),
                    loader,
                )
            with engine.begin() as c:
                for role in [
                    "WAREHOUSE_MANAGER",
                    "BUYER",
                    "SELLER",
                    "RECEIVER",
                    "PICKER",
                    "CONTROLLER",
                    "DIRECTOR",
                    "AUDITOR",
                ]:
                    c.execute(
                        text("""INSERT INTO wms.user_role_grant(id,user_id,role_id,scope_kind,warehouse_id,valid_from,granted_by)
                        SELECT :id,:user,id,'WAREHOUSE',:warehouse,now(),:user FROM wms.role WHERE code=:role"""),
                        dict(id=uuid4(), user=actor, warehouse=warehouse["id"], role=role),
                    )
        for ref in sorted({r["codCustomer"].strip() for g in groups.values() for r in g}):
            clients[ref] = create("master/partners", code=ref, name="Khách hàng " + ref, is_customer=True)[
                "id"
            ]
    manifest["products"] = products
    manifest["warehouses"] = warehouses
    manifest["clients"] = clients
    manifest["quality"] = seed_quality(
        engine, settings, username, prefix=PREFIX, reason="Tiếp nhận và kiểm định hàng"
    )
    manifest["workflows"] = seed_workflows(
        engine, settings, username, prefix=PREFIX, reason="Điều phối hàng và kiểm soát kho"
    )
    return manifest


def import_orders(engine, settings, folder, manifest, progress=print):
    """Import every positive source order, preserving originals and an order crosswalk."""
    if not engine.url.database.startswith(("wms_dataset_", "wms_test_")):
        raise ValueError("Only an isolated dataset/test database is allowed")
    for name, digest in manifest["files"].items():
        if hashlib.sha256((folder / name).read_bytes()).hexdigest() != digest:
            raise ValueError("Source files changed after preparation")
    with engine.connect() as c:
        if c.execute(text("SELECT count(*) FROM wms.document WHERE reason LIKE 'Đơn nguồn %'")).scalar_one():
            raise ValueError("Source orders already exist; reconcile before continuing a partial import")
    _, _, _, groups = read_source(folder)
    products, clients = manifest["products"], manifest["clients"]
    warehouse = manifest["warehouses"][0]["id"]
    mapping = []
    for start in range(0, len(groups), 1000):
        with maintenance(engine, settings, workflows=True, warehouse_prefix=PREFIX) as (request, tokens, _):
            token = tokens[0]
            for number, group in list(groups.items())[start : start + 1000]:
                quantities = Counter()
                for row in group:
                    quantities[row["Reference"]] += int(row["quantity (units)"])
                quantities = {ref: q for ref, q in quantities.items() if q > 0}
                if not quantities:
                    mapping.append(dict(source=number, status="ZERO_QUANTITY", rows=len(group)))
                    continue
                first = group[0]
                order = request(
                    "POST",
                    "sales-orders",
                    dict(
                        warehouse_id=warehouse,
                        partner_id=clients[first["codCustomer"].strip()],
                        business_date=str(datetime.strptime(first["creationDate"], "%d/%m/%Y %H:%M").date()),
                        reason="Đơn nguồn "
                        + number
                        + "; đợt soạn "
                        + ", ".join(sorted({r["waveNumber"] for r in group})),
                        lines=[
                            dict(
                                product_id=products[ref]["id"],
                                product_uom_id=products[ref]["unit"],
                                quantity=str(q),
                                owner_id=str(COMPANY_OWNER),
                            )
                            for ref, q in quantities.items()
                        ],
                    ),
                    token,
                    201,
                )
                mapping.append(
                    dict(source=number, id=order["id"], rows=len(group), units=sum(quantities.values()))
                )
        progress(f"Source orders imported: {min(start + 1000, len(groups))}/{len(groups)}", flush=True)
    return mapping

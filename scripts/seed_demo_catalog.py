"""Seed an EMPTY demo database via WMS services; never modify the operational DB.

Database name must start with wms_demo_ (or wms_test_ for automated verification).
The operator copies the user's identity into the demo database before invoking this.
Bootstrap accounts/permissions are synthetic, audited and disabled after seeding.
Stock is created through normal OPENING create/submit/approve/post operations.
"""

import argparse
import json
import secrets
from datetime import date
from pathlib import Path
from uuid import uuid4

import pyotp
from fastapi.testclient import TestClient
from sqlalchemy import text

from apps.server.api.app import create_app
from apps.server.bootstrap_period import provision
from apps.server.infrastructure.config import Settings
from apps.server.infrastructure.credentials import hash_password
from apps.server.infrastructure.database import make_engine
from packages.contracts.traceability import COMPANY_OWNER

REASON = "DEMO: dữ liệu thực hành InternTechLead; không phải tồn kho thực tế"
WAREHOUSES = [
    ("DEMO-DT", "Kho mẫu Đông Thạnh", "Đông Thạnh, Hóc Môn, TP.HCM"),
    ("DEMO-TD", "Kho mẫu Thủ Đức", "Thủ Đức, TP.HCM — địa chỉ minh họa"),
    ("DEMO-BD", "Kho mẫu Bình Dương", "Bình Dương — địa chỉ minh họa"),
]
FAMILIES = [
    (
        "ssd",
        "SSD SATA",
        "Ổ cứng SSD",
        "SERIAL",
        ["120 GB", "240 GB", "480 GB", "960 GB"],
        "SATA III 6 Gb/s; kích thước 2,5 inch; bộ nhớ flash; dùng cho máy tính hỗ trợ SATA",
        "Nâng cấp lưu trữ máy tính văn phòng. Kiểm tra đầu nối SATA, khay 2,5 inch và sao lưu dữ liệu trước lắp đặt.",
    ),
    (
        "usb",
        "USB lưu trữ",
        "USB và lưu trữ rời",
        "NONE",
        ["16 GB", "32 GB", "64 GB", "128 GB"],
        "USB-A; USB 3.0; định dạng exFAT; vỏ nhựa; có nắp bảo vệ",
        "Trao đổi tệp giữa các máy tính. Tháo thiết bị an toàn sau khi ghi; không dùng làm bản sao lưu duy nhất.",
    ),
    (
        "keyboard",
        "Bàn phím văn phòng",
        "Bàn phím",
        "NONE",
        ["78 phím", "87 phím", "98 phím", "104 phím"],
        "Bố cục QWERTY; kết nối Bluetooth; phím chức năng; dùng cho Windows/macOS/Linux có Bluetooth",
        "Nhập liệu văn phòng và vận hành WMS. Kiểm tra bố cục phím, ghép nối và mức pin trước bàn giao.",
    ),
    (
        "mouse",
        "Chuột máy tính",
        "Chuột",
        "NONE",
        ["800 DPI", "1200 DPI", "1600 DPI", "2400 DPI"],
        "USB-A có dây; cảm biến quang; nút cuộn; hỗ trợ HID trên Windows/macOS/Linux",
        "Điều khiển con trỏ và chọn chứng từ kho. Dùng trên mặt phẳng; giữ sạch cảm biến và tránh gập cáp.",
    ),
    (
        "cable",
        "Cáp mạng LAN",
        "Cáp và kết nối",
        "NONE",
        ["1 m", "2 m", "3 m", "5 m"],
        "Cat5e U/UTP; hai đầu RJ45; 8 lõi; dùng trong nhà; kết nối Ethernet",
        "Kết nối máy trạm WMS với switch/router. Kiểm tra thông mạch, chốt RJ45 và chiều dài tuyến trước lắp đặt.",
    ),
]


def catalog():
    for group, (key, label, category, tracking, variants, specs, usage) in enumerate(FAMILIES):
        for variant in range(40):
            number = group * 40 + variant + 1
            model = f"ITL-{key.upper()}-{variant + 1:02d}"
            option = variants[variant % len(variants)]
            color = ["Đen", "Trắng", "Xám", "Xanh", "Đỏ"][variant // 4 % 5]
            series = "A" if variant < 20 else "B"
            yield dict(
                sku=f"DEMO-{number:04d}",
                name=f"{label} {option} {model}",
                tracking=tracking,
                category=category,
                image_key=key,
                quantity=str(1 if tracking == "SERIAL" else 10 + number % 91),
                values={
                    "brand": "InternTechLead DEMO",
                    "model": model,
                    "description": f"{label} thuộc bộ sản phẩm thực hành kho InternTechLead. {usage} "
                    f"Biến thể {option}, màu {color.lower()}, dòng {series}. Mã hàng {model} là cấu hình mô phỏng, không phải model thương mại của hãng trong ảnh.",
                    "specifications": f"{specs}. Cấu hình: {option}; màu: {color}; dòng: {series}.",
                    "package_contents": "1 sản phẩm; bao bì bảo vệ; nhãn SKU và hướng dẫn kiểm tra (mô phỏng).",
                    "storage_guide": "Bảo quản nơi khô ráo, tránh nắng và nước; không đè vật nặng; giữ bao bì và tem định danh.",
                    "inspection_guide": "Đối chiếu SKU, ngoại quan và phụ kiện; kiểm tra hoạt động; cách ly nếu thiếu/hỏng. "
                    + ("Ghi nhận serial từng chiếc." if tracking == "SERIAL" else "Đếm theo đơn vị Chiếc."),
                    "warranty_note": "Chính sách đào tạo: 12 tháng giả lập; không phải cam kết bảo hành thực tế hoặc chứng cứ nhà cung cấp.",
                    "origin_note": "Dữ liệu mô phỏng phục vụ thực hành; chưa có xuất xứ/CO/CQ thực tế.",
                    "image_key": key,
                    "data_notice": "DEMO — ảnh minh họa nhóm hàng; thông số và tồn kho mô phỏng.",
                },
            )


def seed(engine, settings, username="kien"):
    if not engine.url.database.startswith(("wms_demo_", "wms_test_")):
        raise ValueError("Refusing to seed a database without a demo/test prefix")
    with engine.begin() as c:
        c.execute(text("SELECT pg_advisory_xact_lock(810082026)"))
        if c.execute(
            text(
                "SELECT (SELECT count(*) FROM wms.warehouse)+(SELECT count(*) FROM wms.product)+(SELECT count(*) FROM wms.document)"
            )
        ).scalar_one():
            raise ValueError("Demo database must have no warehouses/products/documents")
        user_id = c.execute(
            text("SELECT id FROM wms.app_user WHERE username=:name AND is_active"), {"name": username}
        ).scalar_one()
        c.execute(text("UPDATE wms.auth_session SET revoked_at=now() WHERE revoked_at IS NULL"))
        c.execute(
            text(
                "UPDATE wms.auth_delivery SET ciphertext=NULL,completed_at=now(),lease_token=NULL,lease_until=NULL WHERE completed_at IS NULL"
            )
        )
    app = create_app(settings, engine=engine)
    synthetic = []

    def grant(c, user, role, scope="GLOBAL", warehouse=None):
        c.execute(
            text("""INSERT INTO wms.user_role_grant
            (id,user_id,role_id,scope_kind,warehouse_id,valid_from,granted_by)
            SELECT :id,:user,id,:scope,:warehouse,clock_timestamp(),:actor FROM wms.role WHERE code=:role"""),
            dict(id=uuid4(), user=user, scope=scope, warehouse=warehouse, actor=user_id, role=role),
        )

    with TestClient(app) as client:

        def request(method, path, body=None, token=None, expected=200):
            headers = {"Idempotency-Key": str(uuid4())}
            if token:
                headers["Authorization"] = "Bearer " + token
            response = client.request(method, "/api/v1/" + path, json=body, headers=headers)
            if response.status_code != expected:
                error = response.json()
                raise RuntimeError(
                    f"{method} {path}: {response.status_code} {error.get('code')} {error.get('message')}"
                )
            return response.json()

        tokens = []
        for name in ["demo_loader", "demo_reviewer"]:
            ident, password, secret = uuid4(), secrets.token_urlsafe(32), pyotp.random_base32()
            synthetic.append(ident)
            with engine.begin() as c:
                c.execute(
                    text("""INSERT INTO wms.app_user(id,username,display_name,password_hash,is_active,auth_version,created_at)
                    VALUES (:id,:name,:label,:hash,true,0,now())"""),
                    dict(id=ident, name=name, label="DEMO — " + name, hash=hash_password(password)),
                )
                c.execute(
                    text("""INSERT INTO wms.mfa_factor(id,user_id,kind,credential_ciphertext,verified_at)
                    VALUES (:id,:user,'TOTP',:cipher,now())"""),
                    dict(
                        id=uuid4(),
                        user=ident,
                        cipher=app.state.identity.cipher().encrypt(secret.encode()).decode(),
                    ),
                )
                for role in ["SYSADMIN", "MASTER_DATA"]:
                    grant(c, ident, role)
                for role in ["CONTROLLER", "DIRECTOR"]:
                    grant(c, ident, role, "ALL_WAREHOUSES")
            login = request(
                "POST", "auth/login", dict(username=name, password=password, device_id=str(uuid4()))
            )
            authenticated = request(
                "POST",
                "auth/mfa",
                dict(challenge_token=login["challenge_token"], code=pyotp.TOTP(secret).now()),
            )
            tokens.append(authenticated["access_token"])
        loader, reviewer = tokens

        def master(resource, **body):
            return request("POST", "master/" + resource, {"reason": REASON, **body}, loader, 201)

        unit = master("uoms", code="DEMO-EA", name="Chiếc", decimal_places=0)
        categories = {
            category: master("categories", code="DEMO-" + key.upper(), name=category)
            for key, _, category, *_ in FAMILIES
        }
        fields = [
            ("brand", "Thương hiệu"),
            ("model", "Model"),
            ("description", "Mô tả sản phẩm"),
            ("specifications", "Thông số kỹ thuật"),
            ("package_contents", "Đóng gói / phụ kiện"),
            ("storage_guide", "Bảo quản"),
            ("inspection_guide", "Kiểm tra khi nhập kho"),
            ("warranty_note", "Ghi chú bảo hành"),
            ("origin_note", "Nguồn gốc"),
            ("image_key", "Ảnh minh họa"),
            ("data_notice", "Phạm vi dữ liệu"),
        ]
        schema = request(
            "PUT",
            "custom-fields/schemas/PRODUCT",
            dict(
                expected_version=0,
                reason=REASON,
                fields=[dict(code=key, label=label, value_type="TEXT") for key, label in fields],
            ),
            loader,
        )
        products = []
        for item in catalog():
            product = master(
                "products",
                sku=item["sku"],
                name=item["name"],
                base_uom_id=unit["id"],
                category_id=categories[item["category"]]["id"],
                tracking=item["tracking"],
            )
            request(
                "PUT",
                "custom-fields/products/" + product["id"],
                dict(
                    expected_version=product["version"],
                    expected_revision_id=None,
                    revision_id=schema["revision_id"],
                    reason=REASON,
                    values=item["values"],
                ),
                loader,
            )
            conversion = request("GET", "master/product-uoms?product_id=" + product["id"], token=loader)[
                "items"
            ][0]
            master("barcodes", code=item["sku"], product_uom_id=conversion["id"])
            products.append((product, item))
        today = date.today()
        summary = []
        for index, (code, name, address) in enumerate(WAREHOUSES):
            warehouse = master("warehouses", code=code, name=name, address=address)
            zone = master(
                "locations",
                code=code + "-ZONE",
                name="Khu lưu trữ mẫu",
                kind="GROUP",
                warehouse_id=warehouse["id"],
            )
            rack = master(
                "locations",
                code=code + "-RACK",
                name="Dãy kệ mẫu",
                kind="GROUP",
                warehouse_id=warehouse["id"],
                parent_id=zone["id"],
            )
            bins = [
                master(
                    "locations",
                    code=code + "-BIN-" + str(i + 1),
                    name="Kệ mẫu " + str(i + 1),
                    kind="STORAGE",
                    warehouse_id=warehouse["id"],
                    parent_id=rack["id"],
                )
                for i in range(5)
            ]
            for kind, label in [
                ("RECEIVING", "Nhận hàng"),
                ("SHIPPING", "Xuất hàng"),
                ("QUARANTINE", "Cách ly"),
            ]:
                master(
                    "locations", code=code + "-" + kind, name=label, kind=kind, warehouse_id=warehouse["id"]
                )
            provision(engine, code, date(today.year, 1, 1), date(today.year, 12, 31), REASON)
            lines = []
            for number, (product, item) in enumerate(products):
                line = dict(
                    product_id=product["id"],
                    quantity_base=item["quantity"],
                    owner_id=str(COMPANY_OWNER),
                    destination_location_id=bins[number // 40]["id"],
                )
                if item["tracking"] == "SERIAL":
                    line["serial_code"] = code + "-" + item["sku"] + "-001"
                lines.append(line)
            draft = request(
                "POST",
                "openings",
                dict(
                    warehouse_id=warehouse["id"],
                    batch_key=str(uuid4()),
                    business_date=str(today),
                    signed_count_reference="DEMO-SIMULATED-COUNT-" + code,
                    reason=REASON,
                    lines=lines,
                ),
                loader,
                201,
            )
            submitted = request(
                "POST",
                "documents/" + draft["id"] + "/submit",
                dict(expected_version=draft["version"], reason=REASON),
                loader,
            )
            approved = request(
                "POST",
                "approval-requests/" + submitted["approval_request_id"] + "/decide",
                dict(expected_version=submitted["version"], reason=REASON, decision="APPROVE"),
                reviewer,
            )
            posted = request(
                "POST",
                "openings/" + draft["id"] + "/post",
                dict(expected_version=approved["version"], reason=REASON, execution_key=str(uuid4())),
                loader,
            )
            if posted["status"] != "COMPLETED":
                raise RuntimeError("Opening not posted")
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
                    grant(c, user_id, role, "WAREHOUSE", warehouse["id"])
            summary.append(
                dict(
                    code=code,
                    name=name,
                    products=len(products),
                    opening=posted["document_id"] if "document_id" in posted else draft["id"],
                )
            )
        with engine.begin() as c:
            grant(c, user_id, "MASTER_DATA")
            for ident in synthetic:
                c.execute(
                    text("UPDATE wms.app_user SET is_active=false,auth_version=auth_version+1 WHERE id=:id"),
                    dict(id=ident),
                )
                c.execute(
                    text("UPDATE wms.auth_session SET revoked_at=now() WHERE user_id=:id"), dict(id=ident)
                )
            c.execute(
                text("""INSERT INTO wms.audit_event(id,actor_id,action,entity_type,entity_id,request_id,occurred_at,after_data,reason)
                VALUES (:id,:actor,'demo.bootstrap','app_user',:actor,:request,now(),CAST(:data AS jsonb),:reason)"""),
                dict(
                    id=uuid4(),
                    actor=user_id,
                    request=uuid4(),
                    data=json.dumps(
                        dict(warehouses=summary, products=len(products), synthetic_accounts_disabled=True)
                    ),
                    reason=REASON,
                ),
            )
        for script in ["reconcile.sql", "reconcile_ownership.sql"]:
            with engine.connect() as c, c.connection.driver_connection.cursor() as cursor:
                cursor.execute((Path(__file__).resolve().parents[1] / "02_CSDL" / script).read_text())
                while True:
                    if cursor.description and cursor.fetchall():
                        raise RuntimeError("Reconciliation failed: " + script)
                    if not cursor.nextset():
                        break
        return dict(warehouses=summary, products=len(products), reconciliation="PASS", username=username)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", default="kien")
    args = parser.parse_args()
    settings = Settings()
    engine = make_engine(settings)
    try:
        print(json.dumps(seed(engine, settings, args.username), ensure_ascii=False, indent=2))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()

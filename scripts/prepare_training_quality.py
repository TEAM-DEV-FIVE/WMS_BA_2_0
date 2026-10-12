"""Prepare training data through normal APIs, restricted to demo/test databases.

Existing stock, identifiers, immutable ledger and real account credentials are retained.
Synthetic maintenance identities are disabled in finally, including on failure.
"""
import json
import secrets
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from uuid import uuid4

import pyotp
from fastapi.testclient import TestClient
from sqlalchemy import text

from apps.server.api.app import create_app
from apps.server.infrastructure.credentials import hash_password
from packages.contracts.master_data import ProductData
from packages.contracts.traceability import COMPANY_OWNER

REASON = "Dữ liệu thực hành kiểm định InternTechLead; không phải biên bản kiểm tra hàng thực tế"


@contextmanager
def maintenance(engine, settings, username="kien", quality=False, workflows=False, warehouse_prefix="DEMO-", bootstrap=False):
    if not engine.url.database.startswith(("wms_demo_", "wms_test_", "wms_dataset_")):
        raise ValueError("Only demo/test databases are allowed")
    with engine.connect() as c:
        actor = c.execute(text("SELECT id FROM wms.app_user WHERE username=:name AND is_active"), {"name": username}).scalar_one()
        warehouses = list(c.execute(text("SELECT id,code FROM wms.warehouse WHERE code LIKE :prefix ORDER BY code"), {"prefix": warehouse_prefix+"%"}).mappings())
    app = create_app(settings, engine=engine)
    identities = []
    with TestClient(app) as client:
        def request(method, path, body=None, token=None, expected=200):
            headers = {"Idempotency-Key": str(uuid4())}
            if token:
                headers["Authorization"] = "Bearer " + token
            response = client.request(method, "/api/v1/" + path, json=body, headers=headers)
            if response.status_code != expected:
                error = response.json()
                raise RuntimeError(f"{method} {path}: {response.status_code} {error.get('code')} {error.get('message')}")
            return response.json()
        try:
            tokens = []
            profiles = ([
                ["BUYER", "SELLER", "RECEIVER", "WAREHOUSE_MANAGER", "PICKER"],
                ["CONTROLLER", "WAREHOUSE_MANAGER"], ["PICKER"], ["PICKER"], ["DIRECTOR"],
            ] if workflows else [["BUYER", "RECEIVER", "WAREHOUSE_MANAGER"], ["CONTROLLER", "DIRECTOR"]] if quality else [[]])
            for index, roles in enumerate(profiles):
                ident, password, secret = uuid4(), secrets.token_urlsafe(32), pyotp.random_base32()
                identities.append(ident)
                name = "training_" + ident.hex[:16]
                with engine.begin() as c:
                    c.execute(text("""INSERT INTO wms.app_user(id,username,display_name,password_hash,is_active,auth_version,created_at)
                        VALUES (:id,:name,:label,:hash,true,0,now())"""),
                        dict(id=ident, name=name, label=("Đồng bộ dữ liệu " if warehouse_prefix != "DEMO-" else "Chuẩn bị dữ liệu thực hành ") + str(index + 1), hash=hash_password(password)))
                    c.execute(text("""INSERT INTO wms.mfa_factor(id,user_id,kind,credential_ciphertext,verified_at)
                        VALUES (:id,:user,'TOTP',:cipher,now())"""),
                        dict(id=uuid4(), user=ident, cipher=app.state.identity.cipher().encrypt(secret.encode()).decode()))
                    grants = [("MASTER_DATA", None)]
                    if bootstrap:
                        grants += [("SYSADMIN", None)] + [(role, "ALL") for role in set(roles + ["CONTROLLER", "DIRECTOR"])]
                    if quality or workflows:
                        grants += [(role, w["id"]) for w in warehouses for role in roles]
                    for role, warehouse in grants:
                        c.execute(text("""INSERT INTO wms.user_role_grant
                            (id,user_id,role_id,scope_kind,warehouse_id,valid_from,granted_by)
                            SELECT :id,:user,id,:scope,:warehouse,now(),:actor FROM wms.role WHERE code=:role"""),
                            dict(id=uuid4(), user=ident, scope="ALL_WAREHOUSES" if warehouse == "ALL" else "WAREHOUSE" if warehouse else "GLOBAL", warehouse=None if warehouse == "ALL" else warehouse, actor=actor, role=role))
                    c.execute(text("""INSERT INTO wms.audit_event(id,actor_id,action,entity_type,entity_id,request_id,occurred_at,after_data,reason)
                        VALUES (:id,:actor,'training.identity.created','app_user',:target,:request,now(),CAST(:data AS jsonb),:reason)"""),
                        dict(id=uuid4(), actor=actor, target=ident, request=uuid4(), data=json.dumps({"temporary": True}), reason=REASON))
                login = request("POST", "auth/login", dict(username=name, password=password, device_id=str(uuid4())))
                token = request("POST", "auth/mfa", dict(challenge_token=login["challenge_token"], code=pyotp.TOTP(secret).now()))
                tokens.append(token["access_token"])
            yield request, tokens, warehouses
        finally:
            with engine.begin() as c:
                for ident in identities:
                    c.execute(text("UPDATE wms.app_user SET is_active=false,auth_version=auth_version+1 WHERE id=:id"), dict(id=ident))
                    c.execute(text("UPDATE wms.auth_session SET revoked_at=now() WHERE user_id=:id AND revoked_at IS NULL"), dict(id=ident))
                    c.execute(text("UPDATE wms.user_role_grant SET revoked_at=now() WHERE user_id=:id AND revoked_at IS NULL"), dict(id=ident))


def clean_product_names(engine, settings, username="kien"):
    count = 0
    with maintenance(engine, settings, username) as (request, tokens, _):
        token = tokens[0]
        after = None
        while True:
            page = request("GET", "master/products?limit=200" + ("&after=" + after if after else ""), token=token)
            for product in page["items"]:
                name = product["name"].replace(" · ", " ")
                if name == product["name"]:
                    continue
                payload = ProductData.model_validate({key: product[key] for key in ProductData.model_fields}).model_dump(mode="json")
                request("PUT", "master/products/" + product["id"],
                        {**payload, "name": name, "expected_version": product["version"], "reason": "Bỏ dấu chấm phân cách trong tên sản phẩm theo yêu cầu chủ dự án"}, token)
                count += 1
            after = page["next_after"]
            if not after:
                break
    return {"renamed_products": count}


def seed_quality(engine, settings, username="kien", products_per_warehouse=200, *, prefix="DEMO-", reason=REASON):
    if not engine.url.database.startswith(("wms_demo_", "wms_test_", "wms_dataset_")):
        raise ValueError("Only demo/test databases are allowed")
    if not 1 <= products_per_warehouse <= 200:
        raise ValueError("Choose between 1 and 200 products per warehouse")
    with engine.connect() as c:
        if c.execute(text("SELECT count(*) FROM wms.audit_event WHERE action='training.quality.completed'")).scalar_one():
            raise ValueError("Quality training has already been prepared")
        # Refuse to repeat a partial run: inspect existing documents before retrying.
        if c.execute(text("SELECT count(*) FROM wms.document WHERE reason=:reason"), dict(reason=reason)).scalar_one():
            raise ValueError("A previous preparation exists; review before retrying")
    summaries = []
    with maintenance(engine, settings, username, quality=True, warehouse_prefix=prefix) as (request, tokens, warehouses):
        loader, reviewer = tokens
        with engine.connect() as c:
            products = list(c.execute(text("""SELECT p.id,p.sku,p.tracking,u.id AS product_uom_id
                FROM wms.product p JOIN wms.product_uom u ON u.product_id=p.id AND u.uom_id=p.base_uom_id AND u.is_active
                WHERE p.sku LIKE :prefix AND p.is_active ORDER BY p.sku LIMIT :limit"""), {"limit": products_per_warehouse, "prefix": prefix+"%"}).mappings())
        if not products or not warehouses:
            raise ValueError("Training catalog and warehouses are required")
        partner = request("POST", "master/partners", dict(code="SUPPLIER-QC" if prefix != "DEMO-" else "ITL-TRAINING-SUPPLIER", name="Nhà cung cấp nội bộ" if prefix != "DEMO-" else "Nhà cung cấp thực hành InternTechLead", is_supplier=True, reason=reason), loader, 201)

        def approve(document):
            submitted = request("POST", "documents/" + document["id"] + "/submit", dict(expected_version=document["version"], reason=reason), loader)
            return request("POST", "approval-requests/" + submitted["approval_request_id"] + "/decide",
                           dict(expected_version=submitted["version"], decision="APPROVE", reason=reason), reviewer)

        for warehouse in warehouses:
            wid = str(warehouse["id"])
            with engine.connect() as c:
                location = str(c.execute(text("SELECT id FROM wms.location WHERE warehouse_id=:id AND kind='RECEIVING' AND is_active"), dict(id=warehouse["id"])).scalar_one())
            quantities = {str(p["id"]): "1" if p["tracking"] == "SERIAL" else "20" for p in products}
            po = request("POST", "purchase-orders", dict(warehouse_id=wid, partner_id=partner["id"], business_date=str(date.today()), reason=reason,
                lines=[dict(product_id=str(p["id"]), product_uom_id=str(p["product_uom_id"]), quantity=quantities[str(p["id"])], owner_id=str(COMPANY_OWNER)) for p in products]), loader, 201)
            approve(po)
            po = request("GET", "purchase-orders/" + po["id"], token=loader)
            lines = []
            for line in po["lines"]:
                entry = dict(source_line_id=line["id"], quantity_base=quantities[line["product_id"]], destination_location_id=location)
                if entry["quantity_base"] == "1":
                    entry["serial_code"] = "ITL-QC-" + warehouse["code"].removeprefix("DEMO-") + "-" + str(line["line_no"])
                lines.append(entry)
            receipt = request("POST", "receipts", dict(source_order_id=po["id"], business_date=str(date.today()), reason=reason, lines=lines), loader, 201)
            approved = approve(receipt)
            detail = request("GET", "receipts/" + receipt["id"], token=loader)
            request("POST", "receipts/" + receipt["id"] + "/post", dict(expected_version=approved["version"], execution_key=str(uuid4()), reason=reason,
                lines=[dict(document_line_id=line["id"], quantity_base=quantities[line["product_id"]]) for line in detail["lines"]]), loader)
            sources, after = [], None
            while True:
                page = request("GET", "quality/sources?warehouse_id=" + wid + "&limit=200" + ("&after=" + after if after else ""), token=loader)
                sources += [s for s in page["items"] if s["receipt_id"] == receipt["id"]]
                after = page["next_after"]
                if not after:
                    break
            decisions = 0
            for index, source in enumerate(sources):
                if index % 3 == 0:
                    continue
                fresh = request("GET", "quality/sources/" + source["id"], token=loader)["source"]
                accepted, rejected = ("1", "0") if source["tracking"] == "SERIAL" else ("20", "0") if index % 3 == 1 else ("15", "2")
                result = request("POST", "quality/sources/" + source["id"] + "/decide", dict(expected_version=fresh["version"], accepted_base=accepted, rejected_base=rejected, reason=reason), loader)
                decisions += len(result["decision_ids"])
            summaries.append(dict(warehouse=warehouse["code"], sources=len(sources), decisions=decisions, receipt=receipt["id"]))
        for script in ["reconcile.sql", "reconcile_ownership.sql"]:
            with engine.connect() as c, c.connection.driver_connection.cursor() as cursor:
                cursor.execute((Path(__file__).resolve().parents[1] / "02_CSDL" / script).read_text())
                while True:
                    if cursor.description and cursor.fetchall():
                        raise RuntimeError("Reconciliation failed")
                    if not cursor.nextset():
                        break
        with engine.begin() as c:
            actor = c.execute(text("SELECT id FROM wms.app_user WHERE username=:name"), dict(name=username)).scalar_one()
            c.execute(text("""INSERT INTO wms.audit_event(id,actor_id,action,entity_type,entity_id,request_id,occurred_at,after_data,reason)
                VALUES (:id,:actor,'training.quality.completed','app_user',:actor,:request,now(),CAST(:data AS jsonb),:reason)"""),
                dict(id=uuid4(), actor=actor, request=uuid4(), data=json.dumps(summaries), reason=reason))
    return summaries

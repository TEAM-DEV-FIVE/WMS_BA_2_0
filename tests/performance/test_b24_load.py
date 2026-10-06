import json
import os
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_orders import ok

from scripts.b24_harness import production_workers, reconcile, save_evidence, tls_server
from scripts.b24_load import measure

pytestmark = pytest.mark.integration


def test_15_ccu_verified_tls_real_posting_and_reconcile(request, tmp_path):
    f = request.getfixturevalue("receiving")
    profile = json.loads(Path(__file__).with_name("b24-local.json").read_text())
    # Fast full-regression probe by default; explicitly opt into the published 60-second measurement.
    measured = os.environ.get("WMS_B24_LOAD_PROFILE") == "local"
    if not measured:
        profile.update(warmup_seconds=1, duration_seconds=5, skus=15, name="regression-smoke-15ccu")
    assert profile["ccu"] == 15 and profile["zones"] == 3
    products = [(f.product, f.conversion)]
    for n in range(1, profile["skus"]):
        product = f.master(
            "products",
            sku=f"B24-{n:05}",
            name=f"Sản phẩm {n}",
            base_uom_id=f.product["base_uom_id"],
            tracking="NONE",
        )
        conversion = ok(
            f.client.get(
                "/api/v1/master/product-uoms",
                params={"product_id": product["id"]},
                headers=f.headers["buyer"],
            )
        )["items"][0]
        products.append((product, conversion))
    docks = []
    for n in range(3):
        zone = f.master(
            "locations", code=f"B24-Z{n}", name=f"Phân khu {n}", kind="GROUP", warehouse_id=str(f.warehouse)
        )
        rack = f.master(
            "locations",
            code=f"B24-R{n}",
            name=f"Dãy {n}",
            kind="GROUP",
            warehouse_id=str(f.warehouse),
            parent_id=zone["id"],
        )
        f.master(
            "locations",
            code=f"B24-B{n}",
            name=f"Ô {n}",
            kind="STORAGE",
            warehouse_id=str(f.warehouse),
            parent_id=rack["id"],
        )
        docks.append(
            f.master(
                "locations",
                code=f"B24-IN{n}",
                name=f"Cửa nhận {n}",
                kind="RECEIVING",
                warehouse_id=str(f.warehouse),
            )
        )
    actors = []
    for n in range(profile["ccu"]):
        name = f"load-{n:02}"
        user, _ = f.iam.user(name)
        for role in ["BUYER", "RECEIVER"]:
            f.iam.grant(user, role, f.warehouse)
        headers = f.iam.headers(f.iam.login(name))
        product, conversion = products[n]
        body = deepcopy(f.body)
        body["lines"][0].update(product_id=product["id"], product_uom_id=conversion["id"], quantity="100000")
        po = ok(
            f.client.post(
                "/api/v1/purchase-orders", json=body, headers={**headers, "Idempotency-Key": str(uuid4())}
            ),
            201,
        )
        submitted = ok(
            f.client.post(
                f"/api/v1/documents/{po['id']}/submit",
                json={"expected_version": po["version"], "reason": "B24 setup"},
                headers={**headers, "Idempotency-Key": str(uuid4())},
            )
        )
        po = ok(f.decision(submitted))
        line = ok(f.client.get(f"/api/v1/purchase-orders/{po['id']}", headers=headers))["lines"][0]
        receipt = ok(
            f.client.post(
                "/api/v1/receipts",
                json=dict(
                    source_order_id=po["id"],
                    business_date=profile["business_date"],
                    reason="B24 load setup",
                    lines=[
                        dict(
                            source_line_id=line["id"],
                            quantity_base="100000",
                            destination_location_id=docks[n % 3]["id"],
                        )
                    ],
                ),
                headers={**headers, "Idempotency-Key": str(uuid4())},
            ),
            201,
        )
        submitted = ok(
            f.client.post(
                f"/api/v1/documents/{receipt['id']}/submit",
                json={"expected_version": receipt["version"], "reason": "B24 setup"},
                headers={**headers, "Idempotency-Key": str(uuid4())},
            )
        )
        receipt = ok(f.decision(submitted))
        view = ok(f.client.get(f"/api/v1/receipts/{receipt['id']}", headers=headers))
        actors.append(
            dict(
                warehouse=str(f.warehouse),
                id=receipt["id"],
                version=receipt["version"],
                line=view["lines"][0]["id"],
                headers=headers,
            )
        )
    with tls_server(f.iam, tmp_path / "tls") as server, production_workers(server) as workers:
        result = measure(
            server,
            f.engine,
            actors,
            warmup=profile["warmup_seconds"],
            duration=profile["duration_seconds"],
            seed=profile["seed"],
            think_seconds=profile["think_seconds"],
        )
    result["workers"] = workers
    result["profile"] = profile
    result["reconcile"] = reconcile(f.engine)
    with f.engine.connect() as c:
        result["actual_dataset"] = {
            name: c.execute(text(f"SELECT count(*) FROM wms.{name}")).scalar_one()
            for name in [
                "warehouse",
                "product",
                "location",
                "stock_move",
                "inventory_transaction",
                "auth_session",
            ]
        }
    result["memory_kib"] = {
        line.split(":")[0]: int(line.split()[1])
        for line in Path("/proc/meminfo").read_text().splitlines()
        if line.startswith(("MemTotal:", "MemAvailable:"))
    }
    save_evidence("load-" + profile["name"], result)
    assert not result["failures"] and not result["warmup_failures"], result["statuses"]
    assert result["completed_requests"] > 0 and len(result["runtime_db_backend_pids"]) >= 2
    assert result["actual_dataset"]["stock_move"] == result["successful_posts_including_warmup"]
    assert result["actual_dataset"]["inventory_transaction"] == result["successful_posts_including_warmup"]
    assert result["database_deadlocks_delta"] == 0

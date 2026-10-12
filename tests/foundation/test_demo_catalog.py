from types import SimpleNamespace

import pytest
from sqlalchemy import text

from apps.desktop.views.product_profile import read_photo
from apps.server.infrastructure.config import Settings
from scripts.seed_demo_catalog import catalog, seed


def test_demo_catalog_photos_descriptions_and_target_guard():
    products = list(catalog())
    assert len(products) == len({p["sku"] for p in products}) == 200
    for key in {p["image_key"] for p in products}:
        image, source = read_photo(key)
        assert image.width > 0 and image.height > 0 and source["license"]
    assert read_photo("../../mfa.env") == (None, None)
    for product in products:
        assert len(product["values"]["description"]) > 120
        assert product["values"]["specifications"] and product["values"]["inspection_guide"]
    with pytest.raises(ValueError, match="prefix"):
        seed(SimpleNamespace(url=SimpleNamespace(database="wms")), None)


@pytest.mark.integration
def test_demo_seed_posts_200_products_per_warehouse_and_preserves_user(iam):
    user, _ = iam.user("kien", mfa=True)
    with iam.engine.connect() as c:
        before = c.execute(
            text("SELECT password_hash FROM wms.app_user WHERE id=:id"), dict(id=user)
        ).scalar_one()
        factor = c.execute(
            text("SELECT credential_ciphertext FROM wms.mfa_factor WHERE user_id=:id"), dict(id=user)
        ).scalar_one()
    result = seed(
        iam.engine,
        Settings(
            database_url=iam.engine.url.render_as_string(hide_password=False),
            mfa_encryption_key=iam.service.settings.mfa_encryption_key,
        ),
    )
    assert result["reconciliation"] == "PASS" and result["products"] == 200
    with iam.engine.connect() as c:
        rows = c.execute(
            text("""SELECT l.warehouse_id,count(DISTINCT s.product_id),count(*)
            FROM wms.stock_balance b JOIN wms.stock_item s ON s.id=b.stock_item_id
            JOIN wms.location l ON l.id=b.location_id WHERE b.on_hand>0 GROUP BY l.warehouse_id""")
        ).all()
        assert len(rows) == 3 and all(row[1:] == (200, 200) for row in rows)
        assert (
            c.execute(
                text("SELECT count(*) FROM wms.document WHERE kind='OPENING' AND status='COMPLETED'")
            ).scalar_one()
            == 3
        )
        assert (
            c.execute(
                text("SELECT count(*) FROM wms.app_user WHERE username LIKE 'demo_%' AND is_active")
            ).scalar_one()
            == 0
        )
        assert (
            c.execute(text("SELECT password_hash FROM wms.app_user WHERE id=:id"), dict(id=user)).scalar_one()
            == before
        )
        assert (
            c.execute(
                text("SELECT credential_ciphertext FROM wms.mfa_factor WHERE user_id=:id"), dict(id=user)
            ).scalar_one()
            == factor
        )
        assert (
            c.execute(
                text("SELECT count(*) FROM wms.custom_field_binding WHERE product_id IS NOT NULL")
            ).scalar_one()
            == 200
        )
    from apps.desktop.catalog_display import display_sku, legacy_sku_query
    from scripts.prepare_training_quality import clean_product_names, seed_quality

    assert display_sku("DEMO-0001") == "ITL-0001"
    assert display_sku("VENDOR-DEMO-0001") == "VENDOR-DEMO-0001"
    assert legacy_sku_query("ITL-0001") == "DEMO-0001"
    with iam.engine.begin() as c:
        c.execute(text("UPDATE wms.product SET name='SSD · ITL-SSD-01' WHERE sku='DEMO-0001'"))
    assert clean_product_names(iam.engine, iam.service.settings)["renamed_products"] == 1
    assert clean_product_names(iam.engine, iam.service.settings)["renamed_products"] == 0
    quality = seed_quality(iam.engine, iam.service.settings)
    assert len(quality) == 3 and all(row["sources"] == 200 and row["decisions"] > 133 for row in quality)
    with iam.engine.connect() as c:
        assert c.execute(text("SELECT name FROM wms.product WHERE sku='DEMO-0001'")).scalar_one() == "SSD ITL-SSD-01"
        assert c.execute(text("SELECT count(*) FROM wms.app_user WHERE username LIKE 'training_%' AND is_active")).scalar_one() == 0
        assert c.execute(text("SELECT count(*) FROM wms.document WHERE kind='RECEIPT' AND status='COMPLETED'")).scalar_one() == 3
        assert c.execute(text("SELECT password_hash FROM wms.app_user WHERE id=:id"), dict(id=user)).scalar_one() == before
    with pytest.raises(ValueError, match="already"):
        seed_quality(iam.engine, iam.service.settings)
    with pytest.raises(ValueError, match="must have no"):
        seed(iam.engine, iam.service.settings)


@pytest.mark.gui
def test_product_profile_loads_photo_and_closes_on_session_change():
    import time
    import tkinter as tk

    from apps.desktop.views.product_profile import ProductProfile

    class Api:
        session_generation = 1

        def in_session(self, generation, callback):
            assert generation == self.session_generation
            return callback()

        def get(self, path):
            return {
                "values": {"description": "Nội dung mẫu", "image_key": "ssd"},
                "schema": {"fields": [{"code": "description", "label": "Mô tả"}]},
            }

    root = tk.Tk()
    api = Api()
    profile = ProductProfile(root, api, dict(id="example", sku="DEMO-0001", name="SSD mẫu"))
    try:
        deadline = time.monotonic() + 3
        while profile.photo is None and time.monotonic() < deadline:
            root.update()
            time.sleep(0.02)
        assert profile.photo is not None
        assert "Nội dung mẫu" in profile.text.get("1.0", "end")
        api.session_generation = 2
        deadline = time.monotonic() + 0.3
        while not profile.closed and time.monotonic() < deadline:
            root.update()
            time.sleep(0.02)
        assert profile.closed and profile.photo is None
    finally:
        profile.close()
        root.destroy()

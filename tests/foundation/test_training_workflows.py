import pytest
from sqlalchemy import text

from scripts.prepare_training_quality import seed_quality
from scripts.prepare_training_workflows import seed_workflows
from scripts.seed_demo_catalog import seed


@pytest.mark.integration
def test_training_workflows_cover_three_warehouses_and_reconcile(iam):
    iam.user('kien', mfa=True)
    seed(iam.engine, iam.service.settings)
    seed_quality(iam.engine, iam.service.settings)
    result = seed_workflows(iam.engine, iam.service.settings)
    assert len(result) == 3
    with iam.engine.connect() as c:
        for kind in ('SO','ISSUE','CUSTOMER_RETURN','SUPPLIER_RETURN','INTERNAL_MOVE','TRANSFER','REVERSAL'):
            assert c.execute(text('SELECT count(DISTINCT warehouse_id) FROM wms.document WHERE kind=:kind'), {'kind':kind}).scalar_one() == 3
        assert c.execute(text("SELECT count(*) FROM wms.count_session WHERE status='POSTED'")).scalar_one() == 3
        assert c.execute(text("SELECT count(*) FROM wms.count_location_lock WHERE released_at IS NULL")).scalar_one() == 0
        assert c.execute(text("SELECT count(*) FROM wms.app_user WHERE username LIKE 'training_%' AND is_active")).scalar_one() == 0
    with pytest.raises(ValueError, match='already'):
        seed_workflows(iam.engine, iam.service.settings)

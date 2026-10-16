"""Regressions for SQL semantics found while running the real API suites."""

from apps.server.infrastructure.mysql_sql import translate


def test_update_reads_original_row_before_increment():
    sql = translate("UPDATE wms.auth_login_throttle SET failures=failures+1,blocked_until=CASE WHEN failures+1>=5 THEN :until ELSE NULL END WHERE key=:key")
    assert sql.index("SET `blocked_until`") < sql.index("`failures` = `failures` + 1")


def test_reserved_bind_names_are_preserved_without_rewriting_literals():
    sql = translate("SELECT ':values' AS literal FROM wms.role WHERE id=:grant AND code=:values")
    assert "':values'" in sql and "= :grant" in sql and "= :values" in sql


def test_cast_projection_preserves_postgresql_result_field():
    assert "CAST(`factor` AS CHAR) AS `factor`" in translate("SELECT factor::text FROM wms.product_uom")


def test_json_scalar_aggregation_quotes_strings():
    sql = translate("SELECT jsonb_agg(DISTINCT code) AS codes FROM wms.role")
    assert "JSON_QUOTE(`code`)" in sql and "DISTINCT" in sql


def test_native_json_and_statement_clock():
    sql = translate("SELECT to_jsonb(required_warehouses) AS scope, statement_timestamp() AS at FROM wms.report_snapshot")
    assert "CAST(`required_warehouses` AS JSON)" in sql
    assert "UTC_TIMESTAMP(6)" in sql


def test_calendar_day_difference_uses_business_timezone():
    sql = translate("SELECT CAST(:today AS date)-(posted_at AT TIME ZONE :timezone)::date AS age FROM wms.inventory_transaction")
    assert "DATEDIFF(" in sql and "CONVERT_TZ(" in sql


def test_queue_claim_uses_ordered_index_without_changing_point_locks():
    query = "SELECT * FROM wms.outbox_event WHERE available_at<=clock_timestamp() ORDER BY available_at,id LIMIT 1 FOR UPDATE SKIP LOCKED"
    assert "FORCE INDEX (`ix_outbox_pending`)" in translate(query)
    assert "FORCE INDEX" not in translate("SELECT * FROM wms.outbox_event WHERE id=:id FOR UPDATE")


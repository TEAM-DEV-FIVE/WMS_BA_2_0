-- After EVERY explicit migration, as wms_owner in database wms; transactional.
BEGIN;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA wms FROM PUBLIC;
GRANT USAGE ON SCHEMA public,wms TO wms_app;
GRANT SELECT ON public.wms_schema_migration TO wms_app;
GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA wms TO wms_app;
GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA wms TO wms_app;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA wms FROM PUBLIC;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA wms TO wms_app;
-- Consumption provenance is append-only to the runtime role; services only INSERT it.
REVOKE UPDATE,DELETE ON wms.reservation_consumption FROM wms_app;
-- No owner membership, DDL, TRUNCATE, TRIGGER, or write to schema history.
COMMIT;

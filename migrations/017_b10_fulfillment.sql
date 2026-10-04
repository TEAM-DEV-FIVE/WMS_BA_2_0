-- B10: reservations remain the only balance hold; picking/packing never posts stock.
-- NULL target/status identifies historical rows. Do not invent provenance on upgrade.
ALTER TABLE wms.pick_task
  ADD COLUMN target_quantity numeric(20,6),
  ADD COLUMN consumed_quantity numeric(20,6) NOT NULL DEFAULT 0,
  ADD COLUMN reason text,
  ADD COLUMN created_by uuid REFERENCES wms.app_user(id),
  ADD COLUMN created_at timestamptz,
  ADD CONSTRAINT ck_pick_target CHECK (target_quantity IS NULL OR
    (target_quantity > 0 AND picked_quantity <= target_quantity)),
  ADD CONSTRAINT ck_pick_consumed CHECK (consumed_quantity >= 0 AND consumed_quantity <= picked_quantity);
CREATE INDEX ix_pick_reservation ON wms.pick_task(reservation_id,id);
ALTER TABLE wms.package
  ADD COLUMN status varchar(20),
  ADD COLUMN version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
  ADD COLUMN reason text,
  ADD COLUMN created_by uuid REFERENCES wms.app_user(id),
  ADD COLUMN created_at timestamptz,
  ADD CONSTRAINT ck_package_status CHECK (status IN ('DRAFT','PACKED','CANCELLED'));
ALTER TABLE wms.package_line
  ADD COLUMN pick_task_id uuid REFERENCES wms.pick_task(id),
  ADD COLUMN consumed_quantity numeric(20,6) NOT NULL DEFAULT 0,
  ADD CONSTRAINT ck_package_consumed CHECK (consumed_quantity >= 0 AND consumed_quantity <= quantity);
CREATE INDEX ix_package_line_pick ON wms.package_line(pick_task_id,id);
CREATE TABLE wms.fulfillment_consumption (
  id uuid PRIMARY KEY,
  package_line_id uuid NOT NULL REFERENCES wms.package_line(id),
  reservation_consumption_id uuid NOT NULL REFERENCES wms.reservation_consumption(id),
  quantity numeric(20,6) NOT NULL CHECK (quantity > 0),
  UNIQUE (package_line_id,reservation_consumption_id)
);
CREATE TRIGGER fulfillment_consumption_append_only BEFORE UPDATE OR DELETE ON wms.fulfillment_consumption
  FOR EACH ROW EXECUTE FUNCTION wms.forbid_ledger_mutation();
CREATE INDEX ix_fulfillment_reservation_consumption ON wms.fulfillment_consumption(reservation_consumption_id);

-- Development B11 revision; coordinator assigns the next release number.
CREATE TABLE wms.transfer_line (
 document_line_id uuid PRIMARY KEY REFERENCES wms.document_line(id) ON DELETE CASCADE,
 stock_item_id uuid NOT NULL REFERENCES wms.stock_item(id),
 source_location_id uuid NOT NULL REFERENCES wms.location(id)
);
CREATE TABLE wms.transfer_move (
 move_id uuid PRIMARY KEY REFERENCES wms.stock_move(id),
 dispatch_move_id uuid REFERENCES wms.stock_move(id),
 disposition varchar(20) NOT NULL CHECK (disposition IN ('DISPATCH','GOOD','DAMAGED','LOSS')),
 evidence_ref varchar(2000) NOT NULL CHECK (length(trim(evidence_ref)) > 0),
 CHECK ((disposition='DISPATCH') = (dispatch_move_id IS NULL))
);
CREATE INDEX ix_transfer_move_source ON wms.transfer_move(dispatch_move_id);
CREATE TABLE wms.transfer_discrepancy (
 id uuid PRIMARY KEY,
 transfer_document_id uuid NOT NULL REFERENCES wms.document(id),
 dispatch_move_id uuid NOT NULL REFERENCES wms.stock_move(id),
 kind varchar(20) NOT NULL CHECK (kind IN ('MISSING','DAMAGED')),
 quantity numeric(20,6) NOT NULL CHECK (quantity > 0),
 evidence_ref varchar(2000) NOT NULL CHECK (length(trim(evidence_ref)) > 0),
 recorded_by uuid NOT NULL REFERENCES wms.app_user(id),
 recorded_at timestamptz NOT NULL
);
CREATE TABLE wms.transfer_adjustment (
 document_id uuid PRIMARY KEY REFERENCES wms.document(id),
 source_transfer_id uuid NOT NULL REFERENCES wms.document(id),
 discrepancy_id uuid NOT NULL REFERENCES wms.transfer_discrepancy(id)
);
CREATE INDEX ix_transfer_adjustment_source ON wms.transfer_adjustment(source_transfer_id);
CREATE TRIGGER immutable_transfer_move BEFORE UPDATE OR DELETE ON wms.transfer_move
 FOR EACH ROW EXECUTE FUNCTION wms.forbid_ledger_mutation();
CREATE TRIGGER immutable_transfer_discrepancy BEFORE UPDATE OR DELETE ON wms.transfer_discrepancy
 FOR EACH ROW EXECUTE FUNCTION wms.forbid_ledger_mutation();

WITH created AS (
 INSERT INTO wms.approval_policy(id,document_kind,revision,is_active)
 SELECT '00000000-0000-4110-8000-000000000001','TRANSFER',1,true
 WHERE NOT EXISTS (SELECT 1 FROM wms.approval_policy WHERE document_kind='TRANSFER') RETURNING id
)
INSERT INTO wms.approval_policy_step(id,policy_id,step_no,role_id,alternative_role_id)
 SELECT '00000000-0000-4110-8000-000000000011',p.id,1,r.id,a.id
 FROM created p CROSS JOIN wms.role r CROSS JOIN wms.role a
 WHERE r.code='WAREHOUSE_MANAGER' AND a.code='CONTROLLER';
WITH created AS (
 INSERT INTO wms.approval_policy(id,document_kind,revision,is_active)
 SELECT '00000000-0000-4110-8000-000000000002','ADJUSTMENT',1,true
 WHERE NOT EXISTS (SELECT 1 FROM wms.approval_policy WHERE document_kind='ADJUSTMENT') RETURNING id
)
INSERT INTO wms.approval_policy_step(id,policy_id,step_no,role_id)
 SELECT '00000000-0000-4110-8000-000000000012',p.id,1,r.id
 FROM created p CROSS JOIN wms.role r WHERE r.code='CONTROLLER';
INSERT INTO wms.location(id,code,name,kind,is_active,version)
 VALUES ('00000000-0000-4110-8000-000000000020','WMS-TRANSFER-LOSS','Đối ứng mất hàng chuyển kho','LOSS',true,1);

CREATE FUNCTION wms.guard_transfer_move() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE d wms.document; t wms.inventory_transaction; plan wms.transfer_line; dest wms.location;
BEGIN
 SELECT * INTO t FROM wms.inventory_transaction WHERE id=NEW.transaction_id;
 SELECT * INTO d FROM wms.document WHERE id=t.document_id;
 IF d.kind='TRANSFER' THEN
   SELECT * INTO plan FROM wms.transfer_line WHERE document_line_id=NEW.line_id;
   SELECT * INTO dest FROM wms.location WHERE id=NEW.destination_location_id;
   IF plan.document_line_id IS NULL OR plan.stock_item_id IS DISTINCT FROM NEW.stock_item_id
      OR NEW.reverses_move_id IS NOT NULL
      OR NOT EXISTS(SELECT 1 FROM wms.document_line WHERE id=NEW.line_id AND document_id=d.id)
      OR NOT EXISTS(SELECT 1 FROM wms.location WHERE id=d.transit_location_id AND kind='TRANSIT' AND warehouse_id IS NULL)
      OR ((t.operation='DISPATCH' AND NEW.source_location_id=plan.source_location_id AND NEW.destination_location_id=d.transit_location_id)
           OR (t.operation='ARRIVE' AND NEW.source_location_id=d.transit_location_id AND dest.warehouse_id=d.destination_warehouse_id AND dest.kind IN ('RECEIVING','QUARANTINE'))) IS NOT TRUE THEN
     RAISE EXCEPTION 'Transfer movement does not match approved route' USING ERRCODE='23514';
   END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER validate_transfer_move BEFORE INSERT ON wms.stock_move
 FOR EACH ROW EXECUTE FUNCTION wms.guard_transfer_move();

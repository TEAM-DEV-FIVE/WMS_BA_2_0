BEGIN;
SET search_path TO wms, public;

CREATE TABLE reversal_document (
  document_id uuid PRIMARY KEY REFERENCES document(id),
  source_transaction_id uuid NOT NULL REFERENCES inventory_transaction(id),
  source_version integer NOT NULL CHECK (source_version > 0),
  reversal_reason text NOT NULL CHECK (length(trim(reversal_reason)) > 0)
);
CREATE INDEX ix_reversal_source ON reversal_document(source_transaction_id);
CREATE TABLE reversal_line (
  document_line_id uuid PRIMARY KEY REFERENCES document_line(id) ON DELETE CASCADE,
  source_move_id uuid NOT NULL REFERENCES stock_move(id)
);
CREATE INDEX ix_reversal_line_source ON reversal_line(source_move_id);

-- Never overwrite an operator's existing policy, including disabled policies.
WITH new_policy AS (
 INSERT INTO approval_policy(id,document_kind,revision,is_active)
 SELECT '00000000-0000-4140-8000-000000000001','REVERSAL',1,true
 WHERE NOT EXISTS (SELECT 1 FROM approval_policy WHERE document_kind='REVERSAL') RETURNING id
)
INSERT INTO approval_policy_step(id,policy_id,step_no,role_id)
SELECT '00000000-0000-4140-8000-000000000002',p.id,1,r.id
FROM new_policy p CROSS JOIN role r WHERE r.code='CONTROLLER';

-- The application serializes sources and checks current permissions/approvals.
-- This deferred guard additionally proves a complete, exact inverse at commit.
-- It does not modify an existing ledger row or relax the ownership guard.
CREATE FUNCTION check_reversal_integrity() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, wms, pg_temp AS $$
DECLARE tx inventory_transaction; original inventory_transaction;
BEGIN
  IF TG_TABLE_NAME='inventory_transaction' THEN
    SELECT * INTO tx FROM inventory_transaction WHERE id=NEW.id;
  ELSE
    SELECT * INTO tx FROM inventory_transaction WHERE id=NEW.transaction_id;
  END IF;
  IF tx.operation<>'REVERSE' AND tx.reverses_transaction_id IS NULL THEN
    IF TG_TABLE_NAME='stock_move' THEN
      IF NEW.reverses_move_id IS NOT NULL THEN
        RAISE EXCEPTION 'Inverse move needs reversal transaction' USING ERRCODE='23514';
      END IF;
    END IF;
    RETURN NEW;
  END IF;
  SELECT * INTO original FROM inventory_transaction WHERE id=tx.reverses_transaction_id;
  IF tx.operation<>'REVERSE' OR original.id IS NULL OR original.operation='REVERSE'
     OR original.reverses_transaction_id IS NOT NULL OR tx.business_date<original.business_date
     OR NOT EXISTS (SELECT 1 FROM document d JOIN reversal_document r ON r.document_id=d.id
       WHERE d.id=tx.document_id AND d.kind='REVERSAL' AND r.source_transaction_id=original.id)
     OR NOT EXISTS (SELECT 1 FROM stock_move WHERE transaction_id=original.id)
     OR (SELECT count(*) FROM stock_move WHERE transaction_id=tx.id)<>
        (SELECT count(*) FROM stock_move WHERE transaction_id=original.id)
     OR EXISTS (
       SELECT 1 FROM stock_move m LEFT JOIN stock_move s ON s.id=m.reverses_move_id
       LEFT JOIN reversal_line r ON r.document_line_id=m.line_id
       JOIN document_line l ON l.id=m.line_id
       WHERE m.transaction_id=tx.id AND (s.id IS NULL OR s.transaction_id<>original.id
         OR l.document_id<>tx.document_id OR l.source_line_id IS DISTINCT FROM s.line_id
         OR r.source_move_id IS DISTINCT FROM s.id
         OR (m.stock_item_id,m.source_location_id,m.destination_location_id,m.quantity_base,m.base_uom_id)
            IS DISTINCT FROM (s.stock_item_id,s.destination_location_id,s.source_location_id,s.quantity_base,s.base_uom_id))
     ) THEN
    RAISE EXCEPTION 'Reversal must be the complete exact inverse of one original transaction' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER reversal_transaction_integrity AFTER INSERT ON inventory_transaction
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_reversal_integrity();
CREATE CONSTRAINT TRIGGER reversal_move_integrity AFTER INSERT ON stock_move
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_reversal_integrity();
COMMIT;

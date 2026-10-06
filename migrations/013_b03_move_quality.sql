-- Development revision B03; integrate as the next release revision on the coordinator branch.
CREATE TABLE wms.move_line (
  document_line_id uuid PRIMARY KEY REFERENCES wms.document_line(id) ON DELETE CASCADE,
  stock_item_id uuid NOT NULL REFERENCES wms.stock_item(id),
  source_location_id uuid NOT NULL REFERENCES wms.location(id),
  destination_location_id uuid NOT NULL REFERENCES wms.location(id),
  quality_decision_id uuid REFERENCES wms.quality_decision(id),
  CHECK (source_location_id <> destination_location_id)
);
CREATE INDEX ix_move_line_quality ON wms.move_line(quality_decision_id);
CREATE INDEX ix_move_line_stock ON wms.move_line(stock_item_id);

WITH created AS (
  INSERT INTO wms.approval_policy(id,document_kind,revision,is_active)
  SELECT '00000000-0000-4000-8000-000000000106','INTERNAL_MOVE',1,true
  WHERE NOT EXISTS (SELECT 1 FROM wms.approval_policy WHERE document_kind='INTERNAL_MOVE')
  RETURNING id
)
INSERT INTO wms.approval_policy_step(id,policy_id,step_no,role_id,alternative_role_id)
SELECT '00000000-0000-4000-8000-000000000116',p.id,1,r.id,a.id
FROM created p CROSS JOIN wms.role r CROSS JOIN wms.role a
WHERE r.code='WAREHOUSE_MANAGER' AND a.code='CONTROLLER';

-- Decisions are evidence, never editable quantity/scope. The optional legacy
-- followup pointer may be set once; move_line retains every actual followup.
CREATE FUNCTION wms.guard_quality_decision() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' OR
    (NEW.id,NEW.receipt_move_id,NEW.quantity,NEW.result,NEW.reason,NEW.decided_by,NEW.decided_at)
      IS DISTINCT FROM
    (OLD.id,OLD.receipt_move_id,OLD.quantity,OLD.result,OLD.reason,OLD.decided_by,OLD.decided_at)
    OR (OLD.followup_document_id IS NOT NULL AND NEW.followup_document_id IS DISTINCT FROM OLD.followup_document_id) THEN
    RAISE EXCEPTION 'Quality decision is immutable' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER immutable_quality_decision BEFORE UPDATE OR DELETE ON wms.quality_decision
FOR EACH ROW EXECUTE FUNCTION wms.guard_quality_decision();

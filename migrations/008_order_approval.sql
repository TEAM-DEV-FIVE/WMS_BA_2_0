-- Ordinary orders use the Q04 alternate approver policy; old requests are not retroactively approved.
ALTER TABLE wms.approval_policy_step ADD COLUMN alternative_role_id uuid REFERENCES wms.role(id);
ALTER TABLE wms.approval_step ADD COLUMN alternative_role_id uuid REFERENCES wms.role(id);
ALTER TABLE wms.approval_request ADD COLUMN content_snapshot jsonb;
ALTER TABLE wms.document_line ADD COLUMN closed_base_quantity numeric(20,6) NOT NULL DEFAULT 0
  CHECK (closed_base_quantity >= 0 AND closed_base_quantity <= base_quantity);

CREATE INDEX ix_policy_alternative_role ON wms.approval_policy_step(alternative_role_id);
CREATE INDEX ix_step_alternative_role ON wms.approval_step(alternative_role_id);
CREATE UNIQUE INDEX uq_pending_approval ON wms.approval_request(document_id) WHERE status='PENDING';
CREATE SEQUENCE wms.order_number_seq;

INSERT INTO wms.approval_policy(id,document_kind,revision,is_active)
SELECT '00000000-0000-4000-8000-000000000101','PO',1,true
WHERE NOT EXISTS (SELECT 1 FROM wms.approval_policy WHERE document_kind='PO');
INSERT INTO wms.approval_policy(id,document_kind,revision,is_active)
SELECT '00000000-0000-4000-8000-000000000102','SO',1,true
WHERE NOT EXISTS (SELECT 1 FROM wms.approval_policy WHERE document_kind='SO');
INSERT INTO wms.approval_policy_step(id,policy_id,step_no,role_id,alternative_role_id)
SELECT CASE p.document_kind WHEN 'PO' THEN '00000000-0000-4000-8000-000000000111'::uuid
  ELSE '00000000-0000-4000-8000-000000000112'::uuid END,p.id,1,r.id,a.id
FROM wms.approval_policy p CROSS JOIN wms.role r CROSS JOIN wms.role a
WHERE p.id IN ('00000000-0000-4000-8000-000000000101','00000000-0000-4000-8000-000000000102')
  AND r.code='WAREHOUSE_MANAGER' AND a.code='CONTROLLER';

CREATE FUNCTION wms.guard_approval_snapshot() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' OR (NEW.document_id,NEW.document_version,NEW.policy_id,NEW.requested_by,NEW.created_at,NEW.content_snapshot)
    IS DISTINCT FROM (OLD.document_id,OLD.document_version,OLD.policy_id,OLD.requested_by,OLD.created_at,OLD.content_snapshot) THEN
    RAISE EXCEPTION 'Approval snapshot is immutable' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER immutable_approval_snapshot BEFORE UPDATE OR DELETE ON wms.approval_request
FOR EACH ROW EXECUTE FUNCTION wms.guard_approval_snapshot();

CREATE FUNCTION wms.guard_approval_decision() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' OR OLD.status<>'PENDING' OR
     (NEW.request_id,NEW.step_no,NEW.required_role_id,NEW.alternative_role_id)
     IS DISTINCT FROM (OLD.request_id,OLD.step_no,OLD.required_role_id,OLD.alternative_role_id) THEN
    RAISE EXCEPTION 'Approval decision/roles are immutable' USING ERRCODE='23514';
  END IF;
  IF NEW.status IN ('APPROVED','REJECTED') AND
     (NEW.decided_by IS NULL OR NEW.decided_at IS NULL OR length(trim(COALESCE(NEW.comment,'')))=0) THEN
    RAISE EXCEPTION 'Decision needs actor, time and reason' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER immutable_approval_decision BEFORE UPDATE OR DELETE ON wms.approval_step
FOR EACH ROW EXECUTE FUNCTION wms.guard_approval_decision();

BEGIN;
SET search_path TO wms, public;

ALTER TABLE stock_period ADD COLUMN version integer NOT NULL DEFAULT 1 CHECK (version > 0);
ALTER TABLE count_session ADD COLUMN business_date date NOT NULL DEFAULT CURRENT_DATE;
ALTER TABLE count_session ADD COLUMN reason text NOT NULL DEFAULT 'Legacy count';
ALTER TABLE count_observation ADD COLUMN reason text NOT NULL DEFAULT 'Legacy observation';
CREATE UNIQUE INDEX uq_count_adjustment ON count_session(adjustment_document_id) WHERE adjustment_document_id IS NOT NULL;
INSERT INTO location(id,code,name,kind,is_active,version)
VALUES ('00000000-0000-4130-8000-000000000020','WMS-COUNT-ADJUST','Đối ứng điều chỉnh kiểm kê','LOSS',true,1);

CREATE TABLE count_scope (
  session_id uuid NOT NULL REFERENCES count_session(id),
  location_id uuid NOT NULL REFERENCES location(id),
  PRIMARY KEY(session_id,location_id)
);
-- Preserve legacy frozen scope, including zero-stock locations. Historical
-- frozen/document dates are preferable to the migration-day default for drafts.
INSERT INTO count_scope(session_id,location_id)
SELECT session_id,location_id FROM count_location_lock
UNION SELECT session_id,location_id FROM count_assignment
UNION SELECT session_id,location_id FROM count_line;
UPDATE count_session SET business_date=frozen_at::date WHERE frozen_at IS NOT NULL;
UPDATE count_session s SET business_date=d.business_date FROM document d WHERE d.id=s.adjustment_document_id;
CREATE TABLE count_submission (
  id uuid PRIMARY KEY,
  session_id uuid NOT NULL REFERENCES count_session(id),
  session_version integer NOT NULL CHECK (session_version > 0),
  policy_revision integer NOT NULL CHECK (policy_revision = 1),
  requested_by uuid NOT NULL REFERENCES app_user(id),
  created_at timestamptz NOT NULL,
  content_snapshot jsonb NOT NULL,
  UNIQUE(session_id,session_version)
);
CREATE TABLE count_empty_confirmation (
  id uuid PRIMARY KEY,
  session_id uuid NOT NULL REFERENCES count_session(id),
  location_id uuid NOT NULL REFERENCES location(id),
  counted_by uuid NOT NULL REFERENCES app_user(id),
  counted_at timestamptz NOT NULL,
  reason text NOT NULL,
  UNIQUE(session_id,location_id,counted_by)
);
CREATE TABLE count_decision (
  id uuid PRIMARY KEY,
  submission_id uuid NOT NULL REFERENCES count_submission(id),
  step_no integer NOT NULL CHECK (step_no IN (1,2)),
  decision text NOT NULL CHECK (decision IN ('APPROVE','REJECT')),
  decided_by uuid NOT NULL REFERENCES app_user(id),
  decided_at timestamptz NOT NULL,
  reason text NOT NULL,
  UNIQUE(submission_id,step_no),
  UNIQUE(submission_id,decided_by)
);
CREATE TABLE count_execution (
  session_id uuid PRIMARY KEY REFERENCES count_session(id),
  execution_key uuid NOT NULL,
  request_hash char(64) NOT NULL,
  response jsonb NOT NULL
);
CREATE TABLE period_reopen_confirmation (
  id uuid PRIMARY KEY,
  period_id uuid NOT NULL REFERENCES stock_period(id),
  period_version integer NOT NULL CHECK (period_version > 0),
  confirmed_by uuid NOT NULL REFERENCES app_user(id),
  confirmed_at timestamptz NOT NULL,
  reason text NOT NULL
);

CREATE TRIGGER immutable_count_submission BEFORE UPDATE OR DELETE ON count_submission
FOR EACH ROW EXECUTE FUNCTION forbid_ledger_mutation();
CREATE TRIGGER immutable_count_empty_confirmation BEFORE UPDATE OR DELETE ON count_empty_confirmation
FOR EACH ROW EXECUTE FUNCTION forbid_ledger_mutation();
CREATE TRIGGER immutable_count_decision BEFORE UPDATE OR DELETE ON count_decision
FOR EACH ROW EXECUTE FUNCTION forbid_ledger_mutation();
CREATE TRIGGER immutable_count_execution BEFORE UPDATE OR DELETE ON count_execution
FOR EACH ROW EXECUTE FUNCTION forbid_ledger_mutation();
CREATE TRIGGER immutable_period_confirmation BEFORE UPDATE OR DELETE ON period_reopen_confirmation
FOR EACH ROW EXECUTE FUNCTION forbid_ledger_mutation();

-- Narrow count-only permission; DIRECTOR does not gain transfer loss approval.
INSERT INTO permission(id,code,description,scope_kind)
VALUES ('00000000-0000-4130-8000-000000000001','count.approve','Duyệt kiểm kê hai bước','WAREHOUSE'),
       ('00000000-0000-4130-8000-000000000002','period.create','Mở kỳ kho','WAREHOUSE');
INSERT INTO role_permission(id,role_id,permission_id)
SELECT md5('b13:' || r.code || ':' || p.code)::uuid,r.id,p.id FROM role r CROSS JOIN permission p
WHERE (p.code='count.approve' AND r.code IN ('CONTROLLER','DIRECTOR'))
   OR (p.code='period.create' AND r.code='CONTROLLER')
   OR (p.code='count.snapshot.read' AND r.code='DIRECTOR')
ON CONFLICT DO NOTHING;

-- Keep the established owner guard, adding only approved, frozen, same-owner
-- count adjustments. Ordinary consignment issue/transfer/reversal stay disabled.
CREATE OR REPLACE FUNCTION wms.guard_move_owner() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE item wms.stock_item; line wms.document_line; owner_kind text;
  agreement wms.consignment_agreement; operation_kind text; business_day date;
  destination_warehouse uuid; source_location wms.location; destination_location wms.location; document_kind text;
BEGIN
  SELECT * INTO item FROM wms.stock_item WHERE id=NEW.stock_item_id;
  SELECT * INTO line FROM wms.document_line WHERE id=NEW.line_id;
  IF item.id IS NULL OR line.id IS NULL THEN RETURN NEW; END IF;
  IF (item.owner_id,item.consignment_id) IS DISTINCT FROM (line.owner_id,line.consignment_id) THEN
    RAISE EXCEPTION 'Move and document owner differ' USING ERRCODE='23514';
  END IF;
  SELECT kind INTO owner_kind FROM wms.stock_owner WHERE id=item.owner_id;
  IF owner_kind='UNCLASSIFIED' THEN RAISE EXCEPTION 'Legacy ownership needs reconciliation' USING ERRCODE='23514'; END IF;
  IF owner_kind='CONSIGNOR' THEN
    IF NEW.reverses_move_id IS NOT NULL THEN
      RAISE EXCEPTION 'Consignment reversal policy is not enabled' USING ERRCODE='23514';
    END IF;
    SELECT * INTO agreement FROM wms.consignment_agreement WHERE id=item.consignment_id FOR SHARE;
    SELECT operation,business_date INTO operation_kind,business_day FROM wms.inventory_transaction WHERE id=NEW.transaction_id;
    SELECT warehouse_id INTO destination_warehouse FROM wms.location WHERE id=NEW.destination_location_id;
    IF operation_kind='MOVE' THEN
      SELECT * INTO source_location FROM wms.location WHERE id=NEW.source_location_id;
      SELECT * INTO destination_location FROM wms.location WHERE id=NEW.destination_location_id;
      SELECT d.kind INTO document_kind FROM wms.inventory_transaction t
        JOIN wms.document d ON d.id=t.document_id WHERE t.id=NEW.transaction_id;
      IF document_kind IS DISTINCT FROM 'INTERNAL_MOVE'
         OR source_location.warehouse_id IS DISTINCT FROM agreement.warehouse_id
         OR destination_location.warehouse_id IS DISTINCT FROM agreement.warehouse_id
         OR source_location.kind NOT IN ('STORAGE','RECEIVING','QUARANTINE')
         OR destination_location.kind NOT IN ('STORAGE','RECEIVING','QUARANTINE') THEN
        RAISE EXCEPTION 'Only same-owner physical internal movement is enabled' USING ERRCODE='23514';
      END IF;
    ELSIF operation_kind='ADJUST' THEN
      IF NOT EXISTS (
        SELECT 1 FROM wms.count_session s
        JOIN wms.document d ON d.id=s.adjustment_document_id AND d.kind='ADJUSTMENT' AND d.status='APPROVED'
        JOIN wms.inventory_transaction t ON t.document_id=d.id AND t.id=NEW.transaction_id
        JOIN wms.count_line cl ON cl.session_id=s.id AND cl.stock_item_id=NEW.stock_item_id
        JOIN wms.location loc ON loc.id=cl.location_id AND loc.warehouse_id=s.warehouse_id
        JOIN wms.count_location_lock lk ON lk.session_id=s.id AND lk.location_id=loc.id AND lk.released_at IS NULL
        WHERE s.status='SUBMITTED' AND s.warehouse_id=agreement.warehouse_id AND line.document_id=d.id
          AND loc.kind IN ('STORAGE','RECEIVING','QUARANTINE','SHIPPING')
          AND NEW.quantity_base=abs(cl.approved_quantity-cl.snapshot_quantity)
          AND ((cl.approved_quantity<cl.snapshot_quantity AND NEW.source_location_id=cl.location_id
                AND NEW.destination_location_id='00000000-0000-4130-8000-000000000020')
            OR (cl.approved_quantity>cl.snapshot_quantity AND NEW.destination_location_id=cl.location_id
                AND NEW.source_location_id='00000000-0000-4130-8000-000000000020'))
          AND 2=(SELECT count(*) FROM wms.count_decision cd WHERE cd.decision='APPROVE'
            AND cd.submission_id=(SELECT cs.id FROM wms.count_submission cs WHERE cs.session_id=s.id ORDER BY cs.session_version DESC LIMIT 1))
      ) THEN
        RAISE EXCEPTION 'Consignment adjustment requires approved frozen count evidence' USING ERRCODE='23514';
      END IF;
      destination_warehouse := agreement.warehouse_id;
    ELSIF operation_kind NOT IN ('RECEIVE','OPEN') THEN
      RAISE EXCEPTION 'Consignment outbound/transfer/reversal policy is not enabled' USING ERRCODE='23514';
    END IF;
    IF NOT agreement.is_active OR destination_warehouse IS DISTINCT FROM agreement.warehouse_id
       OR business_day NOT BETWEEN agreement.valid_from AND agreement.valid_until THEN
      RAISE EXCEPTION 'Agreement is inactive, out of date or outside warehouse' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END $$;
COMMIT;

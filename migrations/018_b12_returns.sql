-- B12 development revision; coordinator chooses the next release number.
CREATE TABLE wms.return_document (
  document_id uuid PRIMARY KEY REFERENCES wms.document(id),
  source_document_id uuid NOT NULL REFERENCES wms.document(id),
  CHECK (document_id <> source_document_id)
);
CREATE INDEX ix_return_document_source ON wms.return_document(source_document_id);
CREATE TABLE wms.return_line (
  document_line_id uuid PRIMARY KEY REFERENCES wms.document_line(id) ON DELETE CASCADE,
  source_move_id uuid NOT NULL REFERENCES wms.stock_move(id),
  location_id uuid NOT NULL REFERENCES wms.location(id)
);
CREATE INDEX ix_return_line_source ON wms.return_line(source_move_id);

-- Preserve any operator-configured policy, including inactive policies.
WITH created AS (
  INSERT INTO wms.approval_policy(id,document_kind,revision,is_active)
  SELECT v.id::uuid,v.kind,1,true FROM (VALUES
    ('00000000-0000-4000-8000-000000000112','CUSTOMER_RETURN'),
    ('00000000-0000-4000-8000-000000000113','SUPPLIER_RETURN')) v(id,kind)
  WHERE NOT EXISTS (SELECT 1 FROM wms.approval_policy p WHERE p.document_kind=v.kind)
  RETURNING id,document_kind
)
INSERT INTO wms.approval_policy_step(id,policy_id,step_no,role_id,alternative_role_id)
SELECT CASE WHEN p.document_kind='CUSTOMER_RETURN' THEN '00000000-0000-4000-8000-000000000122'::uuid
       ELSE '00000000-0000-4000-8000-000000000123'::uuid END,p.id,1,r.id,a.id
FROM created p CROSS JOIN wms.role r CROSS JOIN wms.role a
WHERE r.code='WAREHOUSE_MANAGER' AND a.code='CONTROLLER';

-- Development revision reserved for B02. Renumber only before integration/release.
CREATE TABLE wms.issue_document (
  document_id uuid PRIMARY KEY REFERENCES wms.document(id),
  source_order_id uuid NOT NULL REFERENCES wms.document(id),
  CHECK (document_id <> source_order_id)
);
CREATE INDEX ix_issue_source ON wms.issue_document(source_order_id);

-- Never replace a site's existing ISSUE approval policy.
WITH created AS (
  INSERT INTO wms.approval_policy(id,document_kind,revision,is_active)
  SELECT '00000000-0000-4000-8000-000000000105','ISSUE',1,true
  WHERE NOT EXISTS (SELECT 1 FROM wms.approval_policy WHERE document_kind='ISSUE')
  RETURNING id
)
INSERT INTO wms.approval_policy_step(id,policy_id,step_no,role_id,alternative_role_id)
SELECT '00000000-0000-4000-8000-000000000115',p.id,1,r.id,a.id
FROM created p CROSS JOIN wms.role r CROSS JOIN wms.role a
WHERE r.code='WAREHOUSE_MANAGER' AND a.code='CONTROLLER';

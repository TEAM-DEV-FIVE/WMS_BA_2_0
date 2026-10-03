-- Separate typed cutover metadata/plan; quantities and ownership remain on document_line.
CREATE TABLE wms.opening_document (
  document_id uuid PRIMARY KEY REFERENCES wms.document(id),
  warehouse_id uuid NOT NULL REFERENCES wms.warehouse(id),
  batch_key uuid NOT NULL,
  signed_count_reference varchar(2000) NOT NULL CHECK (length(trim(signed_count_reference)) > 0),
  UNIQUE (warehouse_id,batch_key)
);
CREATE TABLE wms.opening_line (
  document_line_id uuid PRIMARY KEY REFERENCES wms.document_line(id) ON DELETE CASCADE,
  destination_location_id uuid NOT NULL REFERENCES wms.location(id),
  lot_code varchar(100),
  serial_code varchar(160),
  manufactured_on date,
  expires_on date,
  CHECK (lot_code IS NULL OR serial_code IS NULL),
  CHECK (manufactured_on IS NULL OR expires_on IS NULL OR manufactured_on <= expires_on)
);
CREATE INDEX ix_opening_line_location ON wms.opening_line(destination_location_id);

INSERT INTO wms.location(id,warehouse_id,parent_id,code,name,kind,is_active,version)
VALUES ('00000000-0000-4000-8000-000000000202',NULL,NULL,'WMS-OPENING','Đối ứng tồn đầu kỳ','OPENING',true,1);

-- Seed only a genuinely new policy. Existing active/inactive custom policies and steps are untouched.
-- UC23 + RBAC: independent CONTROLLER or DIRECTOR, not ordinary document.approve/Q04.
WITH created AS (
  INSERT INTO wms.approval_policy(id,document_kind,revision,is_active)
  SELECT '00000000-0000-4000-8000-000000000104','OPENING',1,true
  WHERE NOT EXISTS (SELECT 1 FROM wms.approval_policy WHERE document_kind='OPENING')
  RETURNING id
)
INSERT INTO wms.approval_policy_step(id,policy_id,step_no,role_id,alternative_role_id)
SELECT '00000000-0000-4000-8000-000000000114',p.id,1,r.id,a.id
FROM created p CROSS JOIN wms.role r CROSS JOIN wms.role a
WHERE r.code='CONTROLLER' AND a.code='DIRECTOR';

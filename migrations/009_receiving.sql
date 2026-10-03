-- Committed execution acknowledgements survive a change of HTTP idempotency key.
ALTER TABLE wms.inventory_transaction ADD COLUMN request_hash char(64);
ALTER TABLE wms.inventory_transaction ADD COLUMN response jsonb;
ALTER TABLE wms.inventory_transaction ADD CONSTRAINT execution_receipt_pair
  CHECK ((request_hash IS NULL) = (response IS NULL));

INSERT INTO wms.location(id,warehouse_id,parent_id,code,name,kind,is_active,version)
VALUES ('00000000-0000-4000-8000-000000000201',NULL,NULL,'WMS-EXTERNAL','Đối ứng nhận hàng','EXTERNAL',true,1);

INSERT INTO wms.approval_policy(id,document_kind,revision,is_active)
SELECT '00000000-0000-4000-8000-000000000103','RECEIPT',1,true
WHERE NOT EXISTS (SELECT 1 FROM wms.approval_policy WHERE document_kind='RECEIPT');
INSERT INTO wms.approval_policy_step(id,policy_id,step_no,role_id,alternative_role_id)
SELECT '00000000-0000-4000-8000-000000000113',p.id,1,r.id,a.id
FROM wms.approval_policy p CROSS JOIN wms.role r CROSS JOIN wms.role a
WHERE p.id='00000000-0000-4000-8000-000000000103'
  AND r.code='WAREHOUSE_MANAGER' AND a.code='CONTROLLER';

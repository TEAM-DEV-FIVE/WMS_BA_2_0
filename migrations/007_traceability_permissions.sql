-- Explicit warehouse permissions for Q02; stock.read alone is insufficient.
INSERT INTO wms.permission(id,code,scope_kind,description) VALUES ('10b5390f-04fb-5f52-9f9e-3ec732c9593f','ownership.read','WAREHOUSE','Đọc phân tách tồn theo chủ sở hữu');
INSERT INTO wms.role_permission(id,role_id,permission_id) SELECT 'e81c64d0-a924-5791-98a8-e5f459a98e40',id,'10b5390f-04fb-5f52-9f9e-3ec732c9593f' FROM wms.role WHERE code='WAREHOUSE_MANAGER';
INSERT INTO wms.role_permission(id,role_id,permission_id) SELECT '3228e519-f9bd-5aec-9546-365f8f65041d',id,'10b5390f-04fb-5f52-9f9e-3ec732c9593f' FROM wms.role WHERE code='CONTROLLER';
INSERT INTO wms.role_permission(id,role_id,permission_id) SELECT '065c07c5-6d1e-5585-b24a-28d4b1db07bb',id,'10b5390f-04fb-5f52-9f9e-3ec732c9593f' FROM wms.role WHERE code='DIRECTOR';
INSERT INTO wms.role_permission(id,role_id,permission_id) SELECT 'b49fb996-3532-565c-bbef-6ace814670c2',id,'10b5390f-04fb-5f52-9f9e-3ec732c9593f' FROM wms.role WHERE code='AUDITOR';
INSERT INTO wms.permission(id,code,scope_kind,description) VALUES ('181db566-da6e-5f4b-b436-8d5cb83c53ac','serial.read','WAREHOUSE','Tra serial và nguồn bảo hành');
INSERT INTO wms.role_permission(id,role_id,permission_id) SELECT 'a7c72e05-e979-53f9-add4-c8864e3cda7b',id,'181db566-da6e-5f4b-b436-8d5cb83c53ac' FROM wms.role WHERE code='RECEIVER';
INSERT INTO wms.role_permission(id,role_id,permission_id) SELECT '31eb9a68-b84e-59c2-a6eb-4d5779b3fe04',id,'181db566-da6e-5f4b-b436-8d5cb83c53ac' FROM wms.role WHERE code='PICKER';
INSERT INTO wms.role_permission(id,role_id,permission_id) SELECT 'f497d966-411c-529e-94cf-855f2efb9297',id,'181db566-da6e-5f4b-b436-8d5cb83c53ac' FROM wms.role WHERE code='WAREHOUSE_MANAGER';
INSERT INTO wms.role_permission(id,role_id,permission_id) SELECT '10c08970-c5f1-5fb2-af6d-01a1f59cb1bf',id,'181db566-da6e-5f4b-b436-8d5cb83c53ac' FROM wms.role WHERE code='CONTROLLER';
INSERT INTO wms.role_permission(id,role_id,permission_id) SELECT '19a9d356-d0cb-5198-b347-36012382815f',id,'181db566-da6e-5f4b-b436-8d5cb83c53ac' FROM wms.role WHERE code='DIRECTOR';
INSERT INTO wms.role_permission(id,role_id,permission_id) SELECT 'eddd005b-9f13-5c88-8793-9cdf2b3f5041',id,'181db566-da6e-5f4b-b436-8d5cb83c53ac' FROM wms.role WHERE code='AUDITOR';
INSERT INTO wms.permission(id,code,scope_kind,description) VALUES ('7fd3fb40-f15b-5f89-a9e9-2b4351367421','warranty.write','WAREHOUSE','Ghi bổ sung chứng cứ bảo hành');
INSERT INTO wms.role_permission(id,role_id,permission_id) SELECT '09dfff09-fcda-5a3b-ba8a-4ed983049fb3',id,'7fd3fb40-f15b-5f89-a9e9-2b4351367421' FROM wms.role WHERE code='WAREHOUSE_MANAGER';
INSERT INTO wms.role_permission(id,role_id,permission_id) SELECT '05a5206b-b644-5a0a-9909-bbaf39d5bdb9',id,'7fd3fb40-f15b-5f89-a9e9-2b4351367421' FROM wms.role WHERE code='CONTROLLER';

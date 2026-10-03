-- TL01 Q04: ordinary document approval by manager OR controller, with SOD enforced in services.
INSERT INTO wms.role_permission(id,role_id,permission_id) SELECT 'dcc98749-f700-5935-99fb-461357272d27',r.id,p.id FROM wms.role r CROSS JOIN wms.permission p WHERE r.code='CONTROLLER' AND p.code='document.approve' ON CONFLICT (role_id,permission_id) DO NOTHING;

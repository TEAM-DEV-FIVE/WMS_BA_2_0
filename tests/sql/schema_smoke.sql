-- Isolated development database only. All fixtures roll back.
BEGIN;
SET search_path TO wms, public;

CREATE FUNCTION pg_temp.expect_error(command text, expected_state text)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE actual_state text;
BEGIN
  BEGIN
    EXECUTE command;
  EXCEPTION WHEN OTHERS THEN
    GET STACKED DIAGNOSTICS actual_state = RETURNED_SQLSTATE;
    IF actual_state = expected_state THEN RETURN; END IF;
    RAISE EXCEPTION 'Expected SQLSTATE %, got %: %', expected_state, actual_state, SQLERRM;
  END;
  RAISE EXCEPTION 'Expected SQLSTATE %, but command succeeded: %', expected_state, command;
END;
$$;

DO $$
DECLARE
  actor uuid := gen_random_uuid(); wh uuid := gen_random_uuid();
  source uuid := gen_random_uuid(); destination uuid := gen_random_uuid();
  unit uuid := gen_random_uuid(); product_id uuid := gen_random_uuid();
  item uuid := gen_random_uuid(); doc uuid := gen_random_uuid();
  line uuid := gen_random_uuid(); txn uuid := gen_random_uuid();
  move uuid := gen_random_uuid(); session_id uuid := gen_random_uuid();
  count_line_id uuid := gen_random_uuid(); relation_name text; operation text;
BEGIN
  IF (SELECT count(*) FROM information_schema.tables WHERE table_schema='wms') <>
       COALESCE(NULLIF(current_setting('wms.test.expected_tables',true),'')::int,56)
     OR (SELECT count(*) FROM information_schema.columns WHERE table_schema='wms') <>
       COALESCE(NULLIF(current_setting('wms.test.expected_columns',true),'')::int,355)
     OR (SELECT count(*) FROM pg_constraint WHERE connamespace='wms'::regnamespace AND contype='f') <>
       COALESCE(NULLIF(current_setting('wms.test.expected_fks',true),'')::int,105)
  THEN RAISE EXCEPTION 'Unexpected schema inventory'; END IF;
  IF (SELECT count(*) FROM role) <> 10 OR (SELECT count(*) FROM permission) <> 56
     OR (SELECT count(*) FROM role_permission) <> 121
  THEN RAISE EXCEPTION 'Unexpected RBAC seed inventory'; END IF;

  INSERT INTO app_user VALUES (actor,'smoke-test','Smoke test','test-placeholder-not-a-login-hash',true,0,now());
  INSERT INTO warehouse VALUES (wh,'TEST','Test warehouse',NULL,true);
  INSERT INTO location VALUES (source,NULL,NULL,'TEST-OPEN','Opening','OPENING',true);
  INSERT INTO location VALUES (destination,wh,NULL,'TEST-STORAGE','Storage','STORAGE',true);
  INSERT INTO uom VALUES (unit,'TEST','Test unit',0);
  INSERT INTO product VALUES (product_id,'TEST','Test product',NULL,unit,'NONE',false,true,1,'{}');
  IF to_regclass('wms.stock_owner') IS NOT NULL THEN
    EXECUTE format('INSERT INTO stock_item(id,product_id,owner_id) VALUES (%L,%L,%L)',item,product_id,'00000000-0000-4000-8000-000000000001');
  ELSE
    INSERT INTO stock_item VALUES (item,product_id,NULL,NULL);
  END IF;
  IF to_regclass('wms.stock_owner') IS NOT NULL THEN
    PERFORM pg_temp.expect_error(format('INSERT INTO stock_item(id,product_id,owner_id) VALUES (gen_random_uuid(),%L,%L)',product_id,'00000000-0000-4000-8000-000000000001'),'23505');
    PERFORM pg_temp.expect_error('INSERT INTO stock_item(id,product_id,owner_id) VALUES (gen_random_uuid(),gen_random_uuid(),''00000000-0000-4000-8000-000000000001'')','23503');
  ELSE
    PERFORM pg_temp.expect_error(format('INSERT INTO stock_item VALUES (gen_random_uuid(),%L,NULL,NULL)',product_id),'23505');
    PERFORM pg_temp.expect_error('INSERT INTO stock_item VALUES (gen_random_uuid(),gen_random_uuid(),NULL,NULL)','23503');
  END IF;

  INSERT INTO product_uom VALUES (gen_random_uuid(),product_id,unit,1,1,true);
  PERFORM pg_temp.expect_error(format(
    'INSERT INTO product_uom VALUES (gen_random_uuid(),%L,%L,1,2,true)', product_id,unit), '23505');

  INSERT INTO document VALUES (doc,'TEST','OPENING','APPROVED',wh,NULL,NULL,NULL,current_date,actor,now(),1,NULL,'{}');
  IF to_regclass('wms.stock_owner') IS NOT NULL THEN
    EXECUTE format('INSERT INTO document_line(id,document_id,line_no,product_id,uom_id,quantity,factor_snapshot,base_quantity,owner_id) VALUES (%L,%L,1,%L,%L,10,1,10,%L)',line,doc,product_id,unit,'00000000-0000-4000-8000-000000000001');
  ELSE
    INSERT INTO document_line VALUES (line,doc,1,product_id,unit,10,1,10,NULL,NULL);
  END IF;
  INSERT INTO inventory_transaction VALUES (txn,doc,gen_random_uuid(),'OPEN',current_date,now(),actor,NULL);
  INSERT INTO stock_move VALUES (move,txn,line,item,source,destination,10,unit,NULL);
  INSERT INTO stock_balance VALUES (gen_random_uuid(),item,destination,10,0,1);
  PERFORM pg_temp.expect_error('UPDATE stock_balance SET on_hand = -1', '23514');
  PERFORM pg_temp.expect_error('UPDATE stock_balance SET reserved = 11', '23514');
  PERFORM pg_temp.expect_error(format(
    'INSERT INTO stock_move VALUES (gen_random_uuid(),%L,%L,%L,%L,%L,0,%L,NULL)',
    txn,line,item,source,destination,unit), '23514');
  PERFORM pg_temp.expect_error(format(
    'INSERT INTO stock_move VALUES (gen_random_uuid(),%L,%L,%L,%L,%L,1,%L,NULL)',
    txn,line,item,destination,destination,unit), '23514');
  PERFORM pg_temp.expect_error(format(
    'INSERT INTO reservation VALUES (gen_random_uuid(),%L,%L,%L,1,1,1,NULL,%L)',
    line,item,destination,actor), '23514');

  INSERT INTO count_session VALUES (session_id,wh,'TEST','FROZEN',actor,now(),NULL,1);
  INSERT INTO count_line VALUES (count_line_id,session_id,item,destination,10,NULL);
  INSERT INTO count_observation VALUES (gen_random_uuid(),count_line_id,1,10,actor,now(),NULL);
  INSERT INTO count_location_lock VALUES (gen_random_uuid(),session_id,destination,now(),NULL);
  PERFORM pg_temp.expect_error(format(
    'INSERT INTO count_location_lock VALUES (gen_random_uuid(),%L,%L,now(),NULL)',
    session_id,destination), '23505');
  INSERT INTO audit_event VALUES (gen_random_uuid(),actor,wh,'SMOKE','document',doc,gen_random_uuid(),now(),NULL,'{}',NULL);
  FOREACH relation_name IN ARRAY ARRAY['stock_move','inventory_transaction','audit_event','count_observation'] LOOP
    FOREACH operation IN ARRAY ARRAY['UPDATE','DELETE'] LOOP
      IF operation = 'UPDATE' THEN
        PERFORM pg_temp.expect_error(format('UPDATE %I SET id = id', relation_name), 'P0001');
      ELSE
        PERFORM pg_temp.expect_error(format('DELETE FROM %I', relation_name), 'P0001');
      END IF;
    END LOOP;
  END LOOP;
END;
$$;

ROLLBACK;

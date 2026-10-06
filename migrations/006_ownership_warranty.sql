-- No ownership inference for legacy rows. Both sentinels are permanent identities.
CREATE TABLE wms.stock_owner (
  id uuid PRIMARY KEY,
  code varchar(80) NOT NULL UNIQUE,
  name varchar(240) NOT NULL,
  kind varchar(20) NOT NULL CHECK (kind IN ('COMPANY','CONSIGNOR','UNCLASSIFIED')),
  partner_id uuid UNIQUE REFERENCES wms.partner(id) ON DELETE RESTRICT,
  is_active boolean NOT NULL DEFAULT true,
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  CHECK ((kind='CONSIGNOR') = (partner_id IS NOT NULL))
);
CREATE UNIQUE INDEX uq_system_owner ON wms.stock_owner(kind) WHERE kind IN ('COMPANY','UNCLASSIFIED');
INSERT INTO wms.stock_owner(id,code,name,kind) VALUES
 ('00000000-0000-4000-8000-000000000001','COMPANY','Hàng thuộc doanh nghiệp','COMPANY'),
 ('00000000-0000-4000-8000-000000000002','UNCLASSIFIED','Chưa phân loại chủ sở hữu','UNCLASSIFIED');

CREATE TABLE wms.consignment_agreement (
  id uuid PRIMARY KEY,
  code varchar(80) NOT NULL UNIQUE,
  owner_id uuid NOT NULL REFERENCES wms.stock_owner(id) ON DELETE RESTRICT,
  warehouse_id uuid NOT NULL REFERENCES wms.warehouse(id) ON DELETE RESTRICT,
  valid_from date NOT NULL,
  valid_until date NOT NULL,
  source_ref text NOT NULL CHECK (length(btrim(source_ref)) >= 3),
  is_active boolean NOT NULL DEFAULT true,
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  CHECK (valid_until >= valid_from)
);
CREATE INDEX ix_agreement_owner ON wms.consignment_agreement(owner_id);
CREATE INDEX ix_agreement_warehouse ON wms.consignment_agreement(warehouse_id);

ALTER TABLE wms.stock_item ADD COLUMN owner_id uuid REFERENCES wms.stock_owner(id) ON DELETE RESTRICT;
ALTER TABLE wms.stock_item ADD COLUMN consignment_id uuid REFERENCES wms.consignment_agreement(id) ON DELETE RESTRICT;
UPDATE wms.stock_item SET owner_id='00000000-0000-4000-8000-000000000002';
ALTER TABLE wms.stock_item ALTER COLUMN owner_id SET NOT NULL;
DROP INDEX wms.uq_stock_item_dimensions;
CREATE UNIQUE INDEX uq_stock_item_dimensions ON wms.stock_item
 (product_id,lot_id,serial_id,owner_id,consignment_id) NULLS NOT DISTINCT;
CREATE INDEX ix_stock_item_owner ON wms.stock_item(owner_id);
CREATE INDEX ix_stock_item_consignment ON wms.stock_item(consignment_id);

ALTER TABLE wms.document_line ADD COLUMN owner_id uuid REFERENCES wms.stock_owner(id) ON DELETE RESTRICT;
ALTER TABLE wms.document_line ADD COLUMN consignment_id uuid REFERENCES wms.consignment_agreement(id) ON DELETE RESTRICT;
UPDATE wms.document_line SET owner_id='00000000-0000-4000-8000-000000000002';
ALTER TABLE wms.document_line ALTER COLUMN owner_id SET NOT NULL;
CREATE INDEX ix_document_line_owner ON wms.document_line(owner_id);
CREATE INDEX ix_document_line_consignment ON wms.document_line(consignment_id);

ALTER TABLE wms.serial ADD COLUMN warranty_version integer NOT NULL DEFAULT 0 CHECK (warranty_version >= 0);
CREATE TABLE wms.serial_warranty_record (
  id uuid PRIMARY KEY,
  serial_id uuid NOT NULL REFERENCES wms.serial(id) ON DELETE RESTRICT,
  receipt_move_id uuid NOT NULL REFERENCES wms.stock_move(id) ON DELETE RESTRICT,
  revision integer NOT NULL CHECK (revision > 0),
  starts_on date,
  ends_on date,
  evidence_ref text CHECK (evidence_ref IS NULL OR length(btrim(evidence_ref)) >= 3),
  recorded_by uuid NOT NULL REFERENCES wms.app_user(id) ON DELETE RESTRICT,
  recorded_at timestamptz NOT NULL,
  reason text NOT NULL CHECK (length(btrim(reason)) >= 3),
  UNIQUE (serial_id,revision),
  CHECK (starts_on IS NULL OR ends_on IS NULL OR ends_on >= starts_on)
);
CREATE INDEX ix_warranty_receipt ON wms.serial_warranty_record(receipt_move_id);
CREATE INDEX ix_warranty_actor ON wms.serial_warranty_record(recorded_by);
CREATE TRIGGER immutable_warranty BEFORE UPDATE OR DELETE ON wms.serial_warranty_record
FOR EACH ROW EXECUTE FUNCTION wms.forbid_ledger_mutation();

CREATE FUNCTION wms.guard_owner_identity() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Owner identity is permanent' USING ERRCODE='23514'; END IF;
  IF (NEW.kind,NEW.partner_id) IS DISTINCT FROM (OLD.kind,OLD.partner_id)
     OR OLD.kind IN ('COMPANY','UNCLASSIFIED') THEN
    RAISE EXCEPTION 'Owner identity is immutable' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER immutable_owner BEFORE UPDATE OR DELETE ON wms.stock_owner
FOR EACH ROW EXECUTE FUNCTION wms.guard_owner_identity();

CREATE FUNCTION wms.guard_stock_identity() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE owner_kind text; agreement_owner uuid; tracking_kind text; related_product uuid;
BEGIN
  IF TG_OP<>'INSERT' THEN
    RAISE EXCEPTION 'Stock identity is immutable; ownership conversion needs a dedicated workflow' USING ERRCODE='23514';
  END IF;
  SELECT kind INTO owner_kind FROM wms.stock_owner WHERE id=NEW.owner_id AND is_active;
  IF owner_kind IS NULL THEN RAISE EXCEPTION 'Unknown or inactive owner' USING ERRCODE='23514'; END IF;
  IF owner_kind='UNCLASSIFIED' THEN
    RAISE EXCEPTION 'Select an explicit owner for new stock' USING ERRCODE='23514';
  END IF;
  IF (owner_kind='CONSIGNOR') IS DISTINCT FROM (NEW.consignment_id IS NOT NULL) THEN
    RAISE EXCEPTION 'Consigned stock requires an agreement' USING ERRCODE='23514';
  END IF;
  IF NEW.consignment_id IS NOT NULL THEN
    SELECT owner_id INTO agreement_owner FROM wms.consignment_agreement WHERE id=NEW.consignment_id;
    IF agreement_owner IS DISTINCT FROM NEW.owner_id THEN
      RAISE EXCEPTION 'Agreement belongs to another owner' USING ERRCODE='23514';
    END IF;
  END IF;
  SELECT tracking INTO tracking_kind FROM wms.product WHERE id=NEW.product_id;
  IF tracking_kind='NONE' AND (NEW.lot_id IS NOT NULL OR NEW.serial_id IS NOT NULL)
     OR tracking_kind='LOT' AND (NEW.lot_id IS NULL OR NEW.serial_id IS NOT NULL)
     OR tracking_kind='SERIAL' AND (NEW.serial_id IS NULL OR NEW.lot_id IS NOT NULL) THEN
    RAISE EXCEPTION 'Tracking does not match SKU' USING ERRCODE='23514';
  END IF;
  IF NEW.lot_id IS NOT NULL THEN
    SELECT product_id INTO related_product FROM wms.lot WHERE id=NEW.lot_id;
    IF related_product IS DISTINCT FROM NEW.product_id THEN RAISE EXCEPTION 'Lot SKU mismatch' USING ERRCODE='23514'; END IF;
  END IF;
  IF NEW.serial_id IS NOT NULL THEN
    SELECT product_id INTO related_product FROM wms.serial WHERE id=NEW.serial_id FOR UPDATE;
    IF related_product IS DISTINCT FROM NEW.product_id THEN RAISE EXCEPTION 'Serial SKU mismatch' USING ERRCODE='23514'; END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER immutable_stock_identity BEFORE INSERT OR UPDATE OR DELETE ON wms.stock_item
FOR EACH ROW EXECUTE FUNCTION wms.guard_stock_identity();

CREATE FUNCTION wms.guard_serial_owner_balance() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE serial_key uuid;
BEGIN
  SELECT serial_id INTO serial_key FROM wms.stock_item WHERE id=NEW.stock_item_id;
  IF serial_key IS NOT NULL THEN
    PERFORM id FROM wms.serial WHERE id=serial_key FOR UPDATE;
    IF NEW.on_hand NOT IN (0,1) OR (NEW.on_hand=1 AND EXISTS (
      SELECT 1 FROM wms.stock_balance b JOIN wms.stock_item i ON i.id=b.stock_item_id
      WHERE i.serial_id=serial_key AND b.id<>NEW.id AND b.on_hand>0
    )) THEN
      RAISE EXCEPTION 'Serial already has a physical position, regardless of owner' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER serial_owner_balance BEFORE INSERT OR UPDATE ON wms.stock_balance
FOR EACH ROW EXECUTE FUNCTION wms.guard_serial_owner_balance();

CREATE FUNCTION wms.guard_move_owner() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE item wms.stock_item; line wms.document_line; owner_kind text;
  agreement wms.consignment_agreement; operation_kind text; business_day date; destination_warehouse uuid;
BEGIN
  SELECT * INTO item FROM wms.stock_item WHERE id=NEW.stock_item_id;
  SELECT * INTO line FROM wms.document_line WHERE id=NEW.line_id;
  IF item.id IS NULL OR line.id IS NULL THEN RETURN NEW; END IF; -- FK reports unknown references.
  IF (item.owner_id,item.consignment_id) IS DISTINCT FROM (line.owner_id,line.consignment_id) THEN
    RAISE EXCEPTION 'Move and document owner differ' USING ERRCODE='23514';
  END IF;
  SELECT kind INTO owner_kind FROM wms.stock_owner WHERE id=item.owner_id;
  IF owner_kind='UNCLASSIFIED' THEN RAISE EXCEPTION 'Legacy ownership needs reconciliation' USING ERRCODE='23514'; END IF;
  IF owner_kind='CONSIGNOR' THEN
    SELECT * INTO agreement FROM wms.consignment_agreement WHERE id=item.consignment_id FOR SHARE;
    SELECT operation,business_date INTO operation_kind,business_day FROM wms.inventory_transaction WHERE id=NEW.transaction_id;
    SELECT warehouse_id INTO destination_warehouse FROM wms.location WHERE id=NEW.destination_location_id;
    IF operation_kind NOT IN ('RECEIVE','OPEN') THEN
      RAISE EXCEPTION 'Consignment outbound/transfer/reversal policy is not enabled' USING ERRCODE='23514';
    END IF;
    IF NOT agreement.is_active OR destination_warehouse IS DISTINCT FROM agreement.warehouse_id
       OR business_day NOT BETWEEN agreement.valid_from AND agreement.valid_until THEN
      RAISE EXCEPTION 'Agreement is inactive, out of date or outside warehouse' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER move_owner BEFORE INSERT ON wms.stock_move FOR EACH ROW EXECUTE FUNCTION wms.guard_move_owner();

CREATE FUNCTION wms.guard_warranty_source() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM wms.stock_move m JOIN wms.stock_item i ON i.id=m.stock_item_id AND i.serial_id=NEW.serial_id
    JOIN wms.inventory_transaction t ON t.id=m.transaction_id AND t.operation='RECEIVE'
    JOIN wms.document d ON d.id=t.document_id AND d.kind='RECEIPT'
    JOIN wms.document_line l ON l.id=m.line_id AND l.document_id=d.id AND l.product_id=i.product_id
    WHERE m.id=NEW.receipt_move_id AND NOT EXISTS(SELECT 1 FROM wms.stock_move r WHERE r.reverses_move_id=m.id)
  ) THEN RAISE EXCEPTION 'Warranty needs a posted receipt source for this serial' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER warranty_source BEFORE INSERT ON wms.serial_warranty_record
FOR EACH ROW EXECUTE FUNCTION wms.guard_warranty_source();

CREATE FUNCTION wms.guard_reservation_owner() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE item wms.stock_item; line wms.document_line; owner_kind text;
BEGIN
  SELECT * INTO item FROM wms.stock_item WHERE id=NEW.stock_item_id;
  SELECT * INTO line FROM wms.document_line WHERE id=NEW.line_id;
  IF item.id IS NULL OR line.id IS NULL THEN RETURN NEW; END IF;
  IF (item.owner_id,item.consignment_id) IS DISTINCT FROM (line.owner_id,line.consignment_id) THEN
    RAISE EXCEPTION 'Reservation owner differs from order line' USING ERRCODE='23514';
  END IF;
  SELECT kind INTO owner_kind FROM wms.stock_owner WHERE id=item.owner_id;
  IF TG_OP='INSERT' AND owner_kind<>'COMPANY' THEN
    RAISE EXCEPTION 'Reservation policy for consigned/unclassified stock is not enabled' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER reservation_owner BEFORE INSERT OR UPDATE ON wms.reservation
FOR EACH ROW EXECUTE FUNCTION wms.guard_reservation_owner();

CREATE FUNCTION wms.guard_agreement_history() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Keep agreement history' USING ERRCODE='23514'; END IF;
  IF (NEW.owner_id,NEW.warehouse_id,NEW.valid_from,NEW.valid_until,NEW.source_ref)
      IS DISTINCT FROM (OLD.owner_id,OLD.warehouse_id,OLD.valid_from,OLD.valid_until,OLD.source_ref)
      AND (EXISTS(SELECT 1 FROM wms.stock_item WHERE consignment_id=OLD.id)
           OR EXISTS(SELECT 1 FROM wms.document_line WHERE consignment_id=OLD.id)) THEN
    RAISE EXCEPTION 'Used agreement terms are immutable' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER agreement_history BEFORE UPDATE OR DELETE ON wms.consignment_agreement
FOR EACH ROW EXECUTE FUNCTION wms.guard_agreement_history();

CREATE FUNCTION wms.guard_document_line_owner() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE owner_kind text; agreement_owner uuid;
BEGIN
  IF TG_OP='UPDATE' AND (NEW.owner_id,NEW.consignment_id) IS NOT DISTINCT FROM (OLD.owner_id,OLD.consignment_id) THEN
    RETURN NEW;
  END IF;
  IF TG_OP='UPDATE' AND (EXISTS(SELECT 1 FROM wms.stock_move WHERE line_id=OLD.id)
                        OR EXISTS(SELECT 1 FROM wms.reservation WHERE line_id=OLD.id)) THEN
    RAISE EXCEPTION 'Posted/reserved line ownership is immutable' USING ERRCODE='23514';
  END IF;
  SELECT kind INTO owner_kind FROM wms.stock_owner WHERE id=NEW.owner_id AND is_active;
  IF owner_kind IS NULL OR owner_kind='UNCLASSIFIED'
     OR (owner_kind='CONSIGNOR') IS DISTINCT FROM (NEW.consignment_id IS NOT NULL) THEN
    RAISE EXCEPTION 'Select an explicit valid owner/agreement' USING ERRCODE='23514';
  END IF;
  IF NEW.consignment_id IS NOT NULL THEN
    SELECT owner_id INTO agreement_owner FROM wms.consignment_agreement WHERE id=NEW.consignment_id;
    IF agreement_owner IS DISTINCT FROM NEW.owner_id THEN
      RAISE EXCEPTION 'Agreement owner differs from document line' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER document_line_owner BEFORE INSERT OR UPDATE ON wms.document_line
FOR EACH ROW EXECUTE FUNCTION wms.guard_document_line_owner();

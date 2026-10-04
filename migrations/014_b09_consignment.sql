-- Release revision 014; development revision was 015, never released.
-- Explicit inbound custody evidence; ownership dimensions remain immutable on each line/item.
CREATE TABLE wms.consignment_receipt (
  document_id uuid PRIMARY KEY REFERENCES wms.document(id),
  warehouse_id uuid NOT NULL REFERENCES wms.warehouse(id),
  batch_key uuid NOT NULL,
  delivery_reference varchar(2000) NOT NULL CHECK (length(trim(delivery_reference)) > 0),
  UNIQUE (warehouse_id,batch_key)
);
CREATE TABLE wms.consignment_receipt_line (
  document_line_id uuid PRIMARY KEY REFERENCES wms.document_line(id) ON DELETE CASCADE,
  destination_location_id uuid NOT NULL REFERENCES wms.location(id),
  lot_code varchar(100),
  serial_code varchar(160),
  manufactured_on date,
  expires_on date,
  CHECK (lot_code IS NULL OR serial_code IS NULL),
  CHECK (manufactured_on IS NULL OR expires_on IS NULL OR manufactured_on <= expires_on)
);
CREATE INDEX ix_consignment_receipt_line_location ON wms.consignment_receipt_line(destination_location_id);

-- Same-identity handling inside the contracted warehouse, without sale or ownership transfer.
CREATE OR REPLACE FUNCTION wms.guard_move_owner() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE item wms.stock_item; line wms.document_line; owner_kind text;
  agreement wms.consignment_agreement; operation_kind text; business_day date; destination_warehouse uuid; source_location wms.location; destination_location wms.location; document_kind text;
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

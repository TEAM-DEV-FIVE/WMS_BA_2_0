-- Additive: historical master data remains active and starts at version 1.
-- Unicode case-insensitive search must also work in clusters initialized with locale C.
CREATE COLLATION wms.catalog_unicode (provider = icu, locale = 'und', deterministic = true);
ALTER TABLE wms.uom ADD COLUMN version integer NOT NULL DEFAULT 1 CHECK (version > 0);
ALTER TABLE wms.uom ADD COLUMN is_active boolean NOT NULL DEFAULT true;
ALTER TABLE wms.product_category ADD COLUMN version integer NOT NULL DEFAULT 1 CHECK (version > 0);
ALTER TABLE wms.product_category ADD COLUMN is_active boolean NOT NULL DEFAULT true;
ALTER TABLE wms.warehouse ADD COLUMN version integer NOT NULL DEFAULT 1 CHECK (version > 0);
ALTER TABLE wms.location ADD COLUMN version integer NOT NULL DEFAULT 1 CHECK (version > 0);
ALTER TABLE wms.partner ADD COLUMN version integer NOT NULL DEFAULT 1 CHECK (version > 0);
ALTER TABLE wms.barcode ADD COLUMN version integer NOT NULL DEFAULT 1 CHECK (version > 0);

-- Revision factors and price sources are historical facts, never overwritten.
CREATE FUNCTION wms.protect_conversion_identity() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Conversion history is immutable';
  END IF;
  IF (NEW.id, NEW.product_id, NEW.uom_id, NEW.factor, NEW.revision)
     IS DISTINCT FROM (OLD.id, OLD.product_id, OLD.uom_id, OLD.factor, OLD.revision) THEN
    RAISE EXCEPTION 'Create a new conversion revision';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER immutable_conversion BEFORE UPDATE OR DELETE ON wms.product_uom
FOR EACH ROW EXECUTE FUNCTION wms.protect_conversion_identity();
CREATE TRIGGER immutable_reference_price BEFORE UPDATE OR DELETE ON wms.reference_price
FOR EACH ROW EXECUTE FUNCTION wms.forbid_ledger_mutation();

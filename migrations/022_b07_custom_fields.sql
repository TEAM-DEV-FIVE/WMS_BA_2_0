-- Development B07 revision. Coordinator assigns the release number.
SET search_path TO wms, public;

CREATE TABLE custom_field_schema (
  id uuid PRIMARY KEY,
  entity_type varchar(40) NOT NULL UNIQUE,
  version integer NOT NULL CHECK (version > 0),
  CHECK (entity_type IN ('PRODUCT','PO','SO','RECEIPT','OPENING','ISSUE','INTERNAL_MOVE',
    'TRANSFER','ADJUSTMENT','CUSTOMER_RETURN','SUPPLIER_RETURN','REVERSAL'))
);
CREATE TABLE custom_field_revision (
  id uuid PRIMARY KEY,
  schema_id uuid NOT NULL REFERENCES custom_field_schema(id),
  version integer NOT NULL CHECK (version > 0),
  created_by uuid NOT NULL REFERENCES app_user(id),
  created_at timestamptz NOT NULL,
  reason text NOT NULL,
  UNIQUE (schema_id,version)
);
ALTER TABLE custom_field_definition
  DROP CONSTRAINT custom_field_definition_entity_type_code_key,
  ADD COLUMN revision_id uuid REFERENCES custom_field_revision(id),
  ADD COLUMN label varchar(120),
  ADD COLUMN visibility varchar(20) NOT NULL DEFAULT 'BUSINESS'
    CHECK (visibility IN ('BUSINESS','PRICE')),
  ADD CONSTRAINT custom_field_managed_definition CHECK (revision_id IS NULL OR
    (label IS NOT NULL AND is_active AND value_type IN ('TEXT','INTEGER','DECIMAL','BOOLEAN','DATE','ENUM')
      AND code ~ '^[a-z][a-z0-9_]{0,59}$')),
  ADD UNIQUE (revision_id,code);
CREATE UNIQUE INDEX custom_field_legacy_code ON custom_field_definition(entity_type,code) WHERE revision_id IS NULL;

CREATE TABLE custom_field_binding (
  id uuid PRIMARY KEY,
  product_id uuid UNIQUE REFERENCES product(id),
  document_id uuid UNIQUE REFERENCES document(id),
  revision_id uuid NOT NULL REFERENCES custom_field_revision(id),
  values jsonb NOT NULL CHECK (jsonb_typeof(values)='object' AND octet_length(values::text)<=65536),
  CHECK ((product_id IS NOT NULL)::integer + (document_id IS NOT NULL)::integer = 1)
);
CREATE TABLE custom_field_change (
  id uuid PRIMARY KEY,
  binding_id uuid NOT NULL REFERENCES custom_field_binding(id),
  revision_id uuid NOT NULL REFERENCES custom_field_revision(id),
  target_version integer NOT NULL CHECK (target_version > 0),
  values jsonb NOT NULL CHECK (jsonb_typeof(values)='object' AND octet_length(values::text)<=65536),
  changed_by uuid NOT NULL REFERENCES app_user(id),
  changed_at timestamptz NOT NULL,
  reason text NOT NULL,
  UNIQUE (binding_id,target_version)
);

CREATE FUNCTION guard_custom_field_history() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Custom field history is append-only' USING ERRCODE='23514';
END $$;
CREATE TRIGGER custom_field_revision_immutable BEFORE UPDATE OR DELETE ON custom_field_revision
  FOR EACH ROW EXECUTE FUNCTION guard_custom_field_history();
CREATE TRIGGER custom_field_change_immutable BEFORE UPDATE OR DELETE ON custom_field_change
  FOR EACH ROW EXECUTE FUNCTION guard_custom_field_history();
CREATE FUNCTION guard_custom_field_definition() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.revision_id IS NOT NULL OR (TG_OP='UPDATE' AND NEW.revision_id IS NOT NULL) THEN
    RAISE EXCEPTION 'Managed definitions are append-only' USING ERRCODE='23514';
  END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER custom_field_definition_immutable BEFORE UPDATE OR DELETE ON custom_field_definition
  FOR EACH ROW EXECUTE FUNCTION guard_custom_field_definition();

CREATE FUNCTION guard_custom_field_binding() RETURNS trigger LANGUAGE plpgsql SET search_path = wms, pg_temp AS $$
DECLARE expected_type text; actual_type text; current_status text;
BEGIN
  IF TG_OP='DELETE' THEN
    RAISE EXCEPTION 'Custom field bindings cannot be deleted' USING ERRCODE='23514';
  END IF;
  IF TG_OP='UPDATE' AND (NEW.id<>OLD.id OR NEW.product_id IS DISTINCT FROM OLD.product_id
      OR NEW.document_id IS DISTINCT FROM OLD.document_id) THEN
    RAISE EXCEPTION 'Custom field target is immutable' USING ERRCODE='23514';
  END IF;
  SELECT s.entity_type INTO expected_type FROM custom_field_revision r
    JOIN custom_field_schema s ON s.id=r.schema_id WHERE r.id=NEW.revision_id;
  IF NEW.document_id IS NOT NULL THEN
    SELECT kind,status INTO actual_type,current_status FROM document WHERE id=NEW.document_id FOR UPDATE;
    IF current_status NOT IN ('DRAFT','REJECTED') THEN
      RAISE EXCEPTION 'Custom fields require a draft document' USING ERRCODE='23514';
    END IF;
  ELSE
    actual_type := 'PRODUCT';
    PERFORM 1 FROM product WHERE id=NEW.product_id FOR UPDATE;
  END IF;
  IF actual_type IS DISTINCT FROM expected_type THEN
    RAISE EXCEPTION 'Custom field scope mismatch' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER custom_field_binding_guard BEFORE INSERT OR UPDATE OR DELETE ON custom_field_binding
  FOR EACH ROW EXECUTE FUNCTION guard_custom_field_binding();

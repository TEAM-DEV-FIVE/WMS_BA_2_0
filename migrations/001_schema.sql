-- WMS-DD-003 v1.0. DDL nền; đọc 01_Tai_lieu/INVARIANTS.md trước khi xây posting service.

-- Chạy trên database trống cho phát triển/UAT. PostgreSQL 15+. Không phải migration nâng cấp DB hiện có.

BEGIN;

CREATE SCHEMA wms;

SET search_path TO wms, public;

CREATE TABLE organization (
  id uuid PRIMARY KEY NOT NULL,
  code varchar(40) NOT NULL,
  name varchar(200) NOT NULL,
  timezone varchar(80) NOT NULL,
  currency char(3) NOT NULL,
  UNIQUE (code)
);

CREATE TABLE app_user (
  id uuid PRIMARY KEY NOT NULL,
  username varchar(100) NOT NULL,
  display_name varchar(200) NOT NULL,
  password_hash text NOT NULL,
  is_active boolean NOT NULL,
  auth_version integer NOT NULL,
  created_at timestamptz NOT NULL,
  UNIQUE (username),
  CHECK (auth_version >= 0)
);

CREATE TABLE role (
  id uuid PRIMARY KEY NOT NULL,
  code varchar(60) NOT NULL,
  name varchar(160) NOT NULL,
  is_active boolean NOT NULL,
  UNIQUE (code)
);

CREATE TABLE permission (
  id uuid PRIMARY KEY NOT NULL,
  code varchar(100) NOT NULL,
  scope_kind varchar(20) NOT NULL,
  description text NOT NULL,
  UNIQUE (code),
  CHECK (scope_kind IN ('WAREHOUSE','GLOBAL'))
);

CREATE TABLE role_permission (
  id uuid PRIMARY KEY NOT NULL,
  role_id uuid NOT NULL,
  permission_id uuid NOT NULL,
  UNIQUE (role_id,permission_id)
);

CREATE TABLE user_role_grant (
  id uuid PRIMARY KEY NOT NULL,
  user_id uuid NOT NULL,
  role_id uuid NOT NULL,
  scope_kind varchar(20) NOT NULL,
  warehouse_id uuid,
  valid_from timestamptz NOT NULL,
  valid_until timestamptz,
  granted_by uuid NOT NULL,
  revoked_at timestamptz,
  CHECK (scope_kind IN ('GLOBAL','WAREHOUSE','ALL_WAREHOUSES')),
  CHECK ((scope_kind = 'WAREHOUSE') = (warehouse_id IS NOT NULL)),
  CHECK (valid_until IS NULL OR valid_until > valid_from)
);

CREATE TABLE auth_session (
  id uuid PRIMARY KEY NOT NULL,
  user_id uuid NOT NULL,
  refresh_hash text NOT NULL,
  device_id uuid NOT NULL,
  auth_version integer NOT NULL,
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz,
  UNIQUE (refresh_hash)
);

CREATE TABLE mfa_factor (
  id uuid PRIMARY KEY NOT NULL,
  user_id uuid NOT NULL,
  kind varchar(30) NOT NULL,
  credential_ciphertext text NOT NULL,
  verified_at timestamptz,
  revoked_at timestamptz
);

CREATE TABLE warehouse (
  id uuid PRIMARY KEY NOT NULL,
  code varchar(40) NOT NULL,
  name varchar(160) NOT NULL,
  address text,
  is_active boolean NOT NULL,
  UNIQUE (code)
);

CREATE TABLE location (
  id uuid PRIMARY KEY NOT NULL,
  warehouse_id uuid,
  parent_id uuid,
  code varchar(80) NOT NULL,
  name varchar(160) NOT NULL,
  kind varchar(20) NOT NULL,
  is_active boolean NOT NULL,
  UNIQUE (code),
  CHECK (kind IN ('GROUP','STORAGE','RECEIVING','QUARANTINE','SHIPPING','TRANSIT','EXTERNAL','LOSS','OPENING')),
  CHECK ((kind IN ('GROUP','STORAGE','RECEIVING','QUARANTINE','SHIPPING')) = (warehouse_id IS NOT NULL)),
  CHECK (parent_id IS NULL OR parent_id <> id)
);

CREATE TABLE uom (
  id uuid PRIMARY KEY NOT NULL,
  code varchar(30) NOT NULL,
  name varchar(80) NOT NULL,
  decimal_places integer NOT NULL,
  UNIQUE (code),
  CHECK (decimal_places BETWEEN 0 AND 6)
);

CREATE TABLE product_category (
  id uuid PRIMARY KEY NOT NULL,
  code varchar(40) NOT NULL,
  name varchar(160) NOT NULL,
  parent_id uuid,
  UNIQUE (code),
  CHECK (parent_id IS NULL OR parent_id <> id)
);

CREATE TABLE product (
  id uuid PRIMARY KEY NOT NULL,
  sku varchar(80) NOT NULL,
  name varchar(240) NOT NULL,
  category_id uuid,
  base_uom_id uuid NOT NULL,
  tracking varchar(10) NOT NULL,
  expiry_required boolean NOT NULL,
  is_active boolean NOT NULL,
  version integer NOT NULL,
  attributes jsonb NOT NULL,
  UNIQUE (sku),
  CHECK (tracking IN ('NONE','LOT','SERIAL')),
  CHECK (NOT expiry_required OR tracking = 'LOT'),
  CHECK (version > 0)
);

CREATE TABLE product_uom (
  id uuid PRIMARY KEY NOT NULL,
  product_id uuid NOT NULL,
  uom_id uuid NOT NULL,
  factor numeric(20,8) NOT NULL,
  revision integer NOT NULL,
  is_active boolean NOT NULL,
  UNIQUE (product_id,uom_id,revision),
  CHECK (factor > 0),
  CHECK (revision > 0)
);

CREATE TABLE barcode (
  id uuid PRIMARY KEY NOT NULL,
  code varchar(160) NOT NULL,
  product_uom_id uuid NOT NULL,
  is_active boolean NOT NULL,
  UNIQUE (code)
);

CREATE TABLE partner (
  id uuid PRIMARY KEY NOT NULL,
  code varchar(60) NOT NULL,
  name varchar(240) NOT NULL,
  is_customer boolean NOT NULL,
  is_supplier boolean NOT NULL,
  tax_code varchar(40),
  address text,
  is_active boolean NOT NULL,
  UNIQUE (code),
  CHECK (is_customer OR is_supplier)
);

CREATE TABLE lot (
  id uuid PRIMARY KEY NOT NULL,
  product_id uuid NOT NULL,
  code varchar(100) NOT NULL,
  manufactured_on date,
  expires_on date,
  version integer NOT NULL,
  UNIQUE (product_id,code),
  CHECK (expires_on IS NULL OR manufactured_on IS NULL OR expires_on >= manufactured_on)
);

CREATE TABLE serial (
  id uuid PRIMARY KEY NOT NULL,
  product_id uuid NOT NULL,
  code varchar(160) NOT NULL,
  UNIQUE (product_id,code)
);

CREATE TABLE stock_item (
  id uuid PRIMARY KEY NOT NULL,
  product_id uuid NOT NULL,
  lot_id uuid,
  serial_id uuid,
  CHECK (NOT (lot_id IS NOT NULL AND serial_id IS NOT NULL))
);

CREATE TABLE reference_price (
  id uuid PRIMARY KEY NOT NULL,
  product_id uuid NOT NULL,
  effective_on date NOT NULL,
  amount numeric(20,4) NOT NULL,
  currency char(3) NOT NULL,
  source text NOT NULL,
  created_by uuid NOT NULL,
  UNIQUE (product_id,effective_on),
  CHECK (amount >= 0)
);

CREATE TABLE document (
  id uuid PRIMARY KEY NOT NULL,
  number varchar(80) NOT NULL,
  kind varchar(30) NOT NULL,
  status varchar(20) NOT NULL,
  warehouse_id uuid NOT NULL,
  destination_warehouse_id uuid,
  transit_location_id uuid,
  partner_id uuid,
  business_date date NOT NULL,
  created_by uuid NOT NULL,
  created_at timestamptz NOT NULL,
  version integer NOT NULL,
  reason text,
  attributes jsonb NOT NULL,
  UNIQUE (number),
  CHECK (kind IN ('PO','SO','RECEIPT','ISSUE','TRANSFER','CUSTOMER_RETURN','SUPPLIER_RETURN','INTERNAL_MOVE','ADJUSTMENT','OPENING','REVERSAL')),
  CHECK (status IN ('DRAFT','SUBMITTED','APPROVED','REJECTED','PARTIAL','COMPLETED','CANCELLED')),
  CHECK (version > 0),
  CHECK ((kind = 'TRANSFER') = (destination_warehouse_id IS NOT NULL AND transit_location_id IS NOT NULL)),
  CHECK (destination_warehouse_id IS NULL OR destination_warehouse_id <> warehouse_id)
);

CREATE TABLE document_line (
  id uuid PRIMARY KEY NOT NULL,
  document_id uuid NOT NULL,
  line_no integer NOT NULL,
  product_id uuid NOT NULL,
  uom_id uuid NOT NULL,
  quantity numeric(20,6) NOT NULL,
  factor_snapshot numeric(20,8) NOT NULL,
  base_quantity numeric(20,6) NOT NULL,
  source_line_id uuid,
  reference_unit_price numeric(20,4),
  UNIQUE (document_id,line_no),
  CHECK (quantity > 0),
  CHECK (factor_snapshot > 0),
  CHECK (base_quantity > 0),
  CHECK (line_no > 0),
  CHECK (source_line_id IS NULL OR source_line_id <> id)
);

CREATE TABLE document_link (
  id uuid PRIMARY KEY NOT NULL,
  document_id uuid NOT NULL,
  related_document_id uuid NOT NULL,
  relation varchar(30) NOT NULL,
  UNIQUE (document_id,related_document_id,relation),
  CHECK (document_id <> related_document_id)
);

CREATE TABLE document_assignment (
  id uuid PRIMARY KEY NOT NULL,
  document_id uuid NOT NULL,
  user_id uuid NOT NULL,
  assigned_by uuid NOT NULL,
  UNIQUE (document_id,user_id)
);

CREATE TABLE inventory_transaction (
  id uuid PRIMARY KEY NOT NULL,
  document_id uuid NOT NULL,
  execution_key uuid NOT NULL,
  operation varchar(30) NOT NULL,
  business_date date NOT NULL,
  posted_at timestamptz NOT NULL,
  posted_by uuid NOT NULL,
  reverses_transaction_id uuid,
  UNIQUE (document_id,execution_key),
  CHECK (operation IN ('RECEIVE','ISSUE','DISPATCH','ARRIVE','MOVE','ADJUST','OPEN','REVERSE'))
);

CREATE TABLE stock_move (
  id uuid PRIMARY KEY NOT NULL,
  transaction_id uuid NOT NULL,
  line_id uuid NOT NULL,
  stock_item_id uuid NOT NULL,
  source_location_id uuid NOT NULL,
  destination_location_id uuid NOT NULL,
  quantity_base numeric(20,6) NOT NULL,
  base_uom_id uuid NOT NULL,
  reverses_move_id uuid,
  CHECK (quantity_base > 0),
  CHECK (source_location_id <> destination_location_id)
);

CREATE TABLE stock_balance (
  id uuid PRIMARY KEY NOT NULL,
  stock_item_id uuid NOT NULL,
  location_id uuid NOT NULL,
  on_hand numeric(20,6) NOT NULL,
  reserved numeric(20,6) NOT NULL,
  version bigint NOT NULL,
  UNIQUE (stock_item_id,location_id),
  CHECK (on_hand >= 0),
  CHECK (reserved >= 0),
  CHECK (reserved <= on_hand),
  CHECK (version >= 0)
);

CREATE TABLE serial_position (
  id uuid PRIMARY KEY NOT NULL,
  serial_id uuid NOT NULL,
  location_id uuid NOT NULL,
  last_move_id uuid NOT NULL,
  UNIQUE (serial_id)
);

CREATE TABLE reservation (
  id uuid PRIMARY KEY NOT NULL,
  line_id uuid NOT NULL,
  stock_item_id uuid NOT NULL,
  location_id uuid NOT NULL,
  quantity numeric(20,6) NOT NULL,
  consumed numeric(20,6) NOT NULL,
  released numeric(20,6) NOT NULL,
  expires_at timestamptz,
  created_by uuid NOT NULL,
  CHECK (quantity > 0),
  CHECK (consumed >= 0),
  CHECK (released >= 0),
  CHECK (consumed + released <= quantity)
);

CREATE TABLE pick_task (
  id uuid PRIMARY KEY NOT NULL,
  reservation_id uuid NOT NULL,
  assigned_to uuid NOT NULL,
  picked_quantity numeric(20,6) NOT NULL,
  status varchar(20) NOT NULL,
  version integer NOT NULL,
  CHECK (picked_quantity >= 0),
  CHECK (status IN ('OPEN','PICKING','DONE','CANCELLED'))
);

CREATE TABLE reservation_consumption (
  id uuid PRIMARY KEY NOT NULL,
  reservation_id uuid NOT NULL,
  move_id uuid NOT NULL,
  quantity numeric(20,6) NOT NULL,
  UNIQUE (reservation_id,move_id),
  CHECK (quantity > 0)
);

CREATE TABLE package (
  id uuid PRIMARY KEY NOT NULL,
  document_id uuid NOT NULL,
  code varchar(100) NOT NULL,
  UNIQUE (document_id,code)
);

CREATE TABLE package_line (
  id uuid PRIMARY KEY NOT NULL,
  package_id uuid NOT NULL,
  document_line_id uuid NOT NULL,
  stock_item_id uuid NOT NULL,
  quantity numeric(20,6) NOT NULL,
  CHECK (quantity > 0)
);

CREATE TABLE quality_decision (
  id uuid PRIMARY KEY NOT NULL,
  receipt_move_id uuid NOT NULL,
  quantity numeric(20,6) NOT NULL,
  result varchar(20) NOT NULL,
  reason text NOT NULL,
  decided_by uuid NOT NULL,
  decided_at timestamptz NOT NULL,
  followup_document_id uuid,
  CHECK (quantity > 0),
  CHECK (result IN ('ACCEPT','REJECT'))
);

CREATE TABLE approval_policy (
  id uuid PRIMARY KEY NOT NULL,
  document_kind varchar(30) NOT NULL,
  revision integer NOT NULL,
  is_active boolean NOT NULL,
  UNIQUE (document_kind,revision)
);

CREATE TABLE approval_policy_step (
  id uuid PRIMARY KEY NOT NULL,
  policy_id uuid NOT NULL,
  step_no integer NOT NULL,
  role_id uuid NOT NULL,
  UNIQUE (policy_id,step_no),
  CHECK (step_no BETWEEN 1 AND 2)
);

CREATE TABLE approval_request (
  id uuid PRIMARY KEY NOT NULL,
  document_id uuid NOT NULL,
  document_version integer NOT NULL,
  policy_id uuid NOT NULL,
  requested_by uuid NOT NULL,
  status varchar(20) NOT NULL,
  created_at timestamptz NOT NULL,
  UNIQUE (document_id,document_version),
  CHECK (status IN ('PENDING','APPROVED','REJECTED','INVALIDATED'))
);

CREATE TABLE approval_step (
  id uuid PRIMARY KEY NOT NULL,
  request_id uuid NOT NULL,
  step_no integer NOT NULL,
  required_role_id uuid NOT NULL,
  status varchar(20) NOT NULL,
  decided_by uuid,
  decided_at timestamptz,
  comment text,
  UNIQUE (request_id,step_no),
  CHECK (step_no BETWEEN 1 AND 2),
  CHECK (status IN ('PENDING','APPROVED','REJECTED'))
);

CREATE TABLE stock_period (
  id uuid PRIMARY KEY NOT NULL,
  warehouse_id uuid NOT NULL,
  starts_on date NOT NULL,
  ends_on date NOT NULL,
  status varchar(10) NOT NULL,
  closed_by uuid,
  closed_at timestamptz,
  UNIQUE (warehouse_id,starts_on),
  CHECK (ends_on >= starts_on),
  CHECK (status IN ('OPEN','CLOSED'))
);

CREATE TABLE count_session (
  id uuid PRIMARY KEY NOT NULL,
  warehouse_id uuid NOT NULL,
  number varchar(80) NOT NULL,
  status varchar(20) NOT NULL,
  created_by uuid NOT NULL,
  frozen_at timestamptz,
  adjustment_document_id uuid,
  version integer NOT NULL,
  UNIQUE (number),
  CHECK (status IN ('DRAFT','FROZEN','COUNTED','SUBMITTED','POSTED','CANCELLED'))
);

CREATE TABLE count_location_lock (
  id uuid PRIMARY KEY NOT NULL,
  session_id uuid NOT NULL,
  location_id uuid NOT NULL,
  locked_at timestamptz NOT NULL,
  released_at timestamptz,
  UNIQUE (session_id,location_id)
);

CREATE TABLE count_assignment (
  id uuid PRIMARY KEY NOT NULL,
  session_id uuid NOT NULL,
  location_id uuid NOT NULL,
  user_id uuid NOT NULL,
  assigned_by uuid NOT NULL,
  UNIQUE (session_id,location_id,user_id)
);

CREATE TABLE count_line (
  id uuid PRIMARY KEY NOT NULL,
  session_id uuid NOT NULL,
  stock_item_id uuid NOT NULL,
  location_id uuid NOT NULL,
  snapshot_quantity numeric(20,6) NOT NULL,
  approved_quantity numeric(20,6),
  UNIQUE (session_id,stock_item_id,location_id),
  CHECK (snapshot_quantity >= 0),
  CHECK (approved_quantity IS NULL OR approved_quantity >= 0)
);

CREATE TABLE count_observation (
  id uuid PRIMARY KEY NOT NULL,
  count_line_id uuid NOT NULL,
  round_no integer NOT NULL,
  quantity numeric(20,6) NOT NULL,
  counted_by uuid NOT NULL,
  counted_at timestamptz NOT NULL,
  scan_event_key uuid,
  UNIQUE (count_line_id,round_no),
  CHECK (round_no > 0),
  CHECK (quantity >= 0)
);

CREATE TABLE idempotency_record (
  id uuid PRIMARY KEY NOT NULL,
  actor_id uuid NOT NULL,
  key uuid NOT NULL,
  command varchar(100) NOT NULL,
  request_hash char(64) NOT NULL,
  response jsonb NOT NULL,
  http_status integer NOT NULL,
  completed_at timestamptz NOT NULL,
  expires_at timestamptz NOT NULL,
  UNIQUE (actor_id,key)
);

CREATE TABLE outbox_event (
  id uuid PRIMARY KEY NOT NULL,
  event_type varchar(100) NOT NULL,
  aggregate_id uuid NOT NULL,
  payload jsonb NOT NULL,
  occurred_at timestamptz NOT NULL,
  available_at timestamptz NOT NULL,
  attempts integer NOT NULL,
  processed_at timestamptz,
  last_error text,
  CHECK (attempts >= 0)
);

CREATE TABLE consumer_receipt (
  id uuid PRIMARY KEY NOT NULL,
  event_id uuid NOT NULL,
  consumer varchar(100) NOT NULL,
  processed_at timestamptz NOT NULL,
  UNIQUE (event_id,consumer)
);

CREATE TABLE audit_event (
  id uuid PRIMARY KEY NOT NULL,
  actor_id uuid,
  warehouse_id uuid,
  action varchar(100) NOT NULL,
  entity_type varchar(80) NOT NULL,
  entity_id uuid,
  request_id uuid NOT NULL,
  occurred_at timestamptz NOT NULL,
  before_data jsonb,
  after_data jsonb,
  reason text
);

CREATE TABLE stored_file (
  id uuid PRIMARY KEY NOT NULL,
  storage_key text NOT NULL,
  original_name varchar(240) NOT NULL,
  mime_type varchar(100) NOT NULL,
  sha256 char(64) NOT NULL,
  size_bytes bigint NOT NULL,
  uploaded_by uuid NOT NULL,
  created_at timestamptz NOT NULL,
  UNIQUE (storage_key),
  CHECK (size_bytes >= 0)
);

CREATE TABLE document_attachment (
  id uuid PRIMARY KEY NOT NULL,
  document_id uuid NOT NULL,
  file_id uuid NOT NULL,
  UNIQUE (document_id,file_id)
);

CREATE TABLE product_image (
  id uuid PRIMARY KEY NOT NULL,
  product_id uuid NOT NULL,
  file_id uuid NOT NULL,
  sort_order integer NOT NULL,
  UNIQUE (product_id,file_id)
);

CREATE TABLE import_job (
  id uuid PRIMARY KEY NOT NULL,
  kind varchar(60) NOT NULL,
  file_id uuid NOT NULL,
  requested_by uuid NOT NULL,
  status varchar(20) NOT NULL,
  file_hash char(64) NOT NULL,
  mapping_version varchar(30) NOT NULL,
  operation_key uuid NOT NULL,
  created_at timestamptz NOT NULL,
  UNIQUE (operation_key)
);

CREATE TABLE import_row (
  id uuid PRIMARY KEY NOT NULL,
  job_id uuid NOT NULL,
  row_no integer NOT NULL,
  payload jsonb NOT NULL,
  errors jsonb NOT NULL,
  target_id uuid,
  status varchar(20) NOT NULL,
  UNIQUE (job_id,row_no)
);

CREATE TABLE export_job (
  id uuid PRIMARY KEY NOT NULL,
  requested_by uuid NOT NULL,
  report_code varchar(40) NOT NULL,
  filters jsonb NOT NULL,
  status varchar(20) NOT NULL,
  file_id uuid,
  created_at timestamptz NOT NULL,
  expires_at timestamptz NOT NULL
);

CREATE TABLE custom_field_definition (
  id uuid PRIMARY KEY NOT NULL,
  entity_type varchar(40) NOT NULL,
  code varchar(60) NOT NULL,
  value_type varchar(20) NOT NULL,
  required boolean NOT NULL,
  validation jsonb NOT NULL,
  is_active boolean NOT NULL,
  UNIQUE (entity_type,code)
);

CREATE TABLE client_release (
  id uuid PRIMARY KEY NOT NULL,
  version varchar(40) NOT NULL,
  os varchar(20) NOT NULL,
  architecture varchar(20) NOT NULL,
  api_major integer NOT NULL,
  sha256 char(64) NOT NULL,
  download_uri text NOT NULL,
  is_minimum boolean NOT NULL,
  UNIQUE (version,os,architecture)
);

ALTER TABLE role_permission ADD FOREIGN KEY (role_id) REFERENCES role(id) ON DELETE RESTRICT;

CREATE INDEX ix_role_permission_role_id ON role_permission (role_id);

ALTER TABLE role_permission ADD FOREIGN KEY (permission_id) REFERENCES permission(id) ON DELETE RESTRICT;

CREATE INDEX ix_role_permission_permission_id ON role_permission (permission_id);

ALTER TABLE user_role_grant ADD FOREIGN KEY (user_id) REFERENCES app_user(id) ON DELETE RESTRICT;

CREATE INDEX ix_user_role_grant_user_id ON user_role_grant (user_id);

ALTER TABLE user_role_grant ADD FOREIGN KEY (role_id) REFERENCES role(id) ON DELETE RESTRICT;

CREATE INDEX ix_user_role_grant_role_id ON user_role_grant (role_id);

ALTER TABLE user_role_grant ADD FOREIGN KEY (warehouse_id) REFERENCES warehouse(id) ON DELETE RESTRICT;

CREATE INDEX ix_user_role_grant_warehouse_id ON user_role_grant (warehouse_id);

ALTER TABLE user_role_grant ADD FOREIGN KEY (granted_by) REFERENCES app_user(id) ON DELETE RESTRICT;

CREATE INDEX ix_user_role_grant_granted_by ON user_role_grant (granted_by);

ALTER TABLE auth_session ADD FOREIGN KEY (user_id) REFERENCES app_user(id) ON DELETE RESTRICT;

CREATE INDEX ix_auth_session_user_id ON auth_session (user_id);

ALTER TABLE mfa_factor ADD FOREIGN KEY (user_id) REFERENCES app_user(id) ON DELETE RESTRICT;

CREATE INDEX ix_mfa_factor_user_id ON mfa_factor (user_id);

ALTER TABLE location ADD FOREIGN KEY (warehouse_id) REFERENCES warehouse(id) ON DELETE RESTRICT;

CREATE INDEX ix_location_warehouse_id ON location (warehouse_id);

ALTER TABLE location ADD FOREIGN KEY (parent_id) REFERENCES location(id) ON DELETE RESTRICT;

CREATE INDEX ix_location_parent_id ON location (parent_id);

ALTER TABLE product_category ADD FOREIGN KEY (parent_id) REFERENCES product_category(id) ON DELETE RESTRICT;

CREATE INDEX ix_product_category_parent_id ON product_category (parent_id);

ALTER TABLE product ADD FOREIGN KEY (category_id) REFERENCES product_category(id) ON DELETE RESTRICT;

CREATE INDEX ix_product_category_id ON product (category_id);

ALTER TABLE product ADD FOREIGN KEY (base_uom_id) REFERENCES uom(id) ON DELETE RESTRICT;

CREATE INDEX ix_product_base_uom_id ON product (base_uom_id);

ALTER TABLE product_uom ADD FOREIGN KEY (product_id) REFERENCES product(id) ON DELETE RESTRICT;

CREATE INDEX ix_product_uom_product_id ON product_uom (product_id);

ALTER TABLE product_uom ADD FOREIGN KEY (uom_id) REFERENCES uom(id) ON DELETE RESTRICT;

CREATE INDEX ix_product_uom_uom_id ON product_uom (uom_id);

ALTER TABLE barcode ADD FOREIGN KEY (product_uom_id) REFERENCES product_uom(id) ON DELETE RESTRICT;

CREATE INDEX ix_barcode_product_uom_id ON barcode (product_uom_id);

ALTER TABLE lot ADD FOREIGN KEY (product_id) REFERENCES product(id) ON DELETE RESTRICT;

CREATE INDEX ix_lot_product_id ON lot (product_id);

ALTER TABLE serial ADD FOREIGN KEY (product_id) REFERENCES product(id) ON DELETE RESTRICT;

CREATE INDEX ix_serial_product_id ON serial (product_id);

ALTER TABLE stock_item ADD FOREIGN KEY (product_id) REFERENCES product(id) ON DELETE RESTRICT;

CREATE INDEX ix_stock_item_product_id ON stock_item (product_id);

ALTER TABLE stock_item ADD FOREIGN KEY (lot_id) REFERENCES lot(id) ON DELETE RESTRICT;

CREATE INDEX ix_stock_item_lot_id ON stock_item (lot_id);

ALTER TABLE stock_item ADD FOREIGN KEY (serial_id) REFERENCES serial(id) ON DELETE RESTRICT;

CREATE INDEX ix_stock_item_serial_id ON stock_item (serial_id);

ALTER TABLE reference_price ADD FOREIGN KEY (product_id) REFERENCES product(id) ON DELETE RESTRICT;

CREATE INDEX ix_reference_price_product_id ON reference_price (product_id);

ALTER TABLE reference_price ADD FOREIGN KEY (created_by) REFERENCES app_user(id) ON DELETE RESTRICT;

CREATE INDEX ix_reference_price_created_by ON reference_price (created_by);

ALTER TABLE document ADD FOREIGN KEY (warehouse_id) REFERENCES warehouse(id) ON DELETE RESTRICT;

CREATE INDEX ix_document_warehouse_id ON document (warehouse_id);

ALTER TABLE document ADD FOREIGN KEY (destination_warehouse_id) REFERENCES warehouse(id) ON DELETE RESTRICT;

CREATE INDEX ix_document_destination_warehouse_id ON document (destination_warehouse_id);

ALTER TABLE document ADD FOREIGN KEY (transit_location_id) REFERENCES location(id) ON DELETE RESTRICT;

CREATE INDEX ix_document_transit_location_id ON document (transit_location_id);

ALTER TABLE document ADD FOREIGN KEY (partner_id) REFERENCES partner(id) ON DELETE RESTRICT;

CREATE INDEX ix_document_partner_id ON document (partner_id);

ALTER TABLE document ADD FOREIGN KEY (created_by) REFERENCES app_user(id) ON DELETE RESTRICT;

CREATE INDEX ix_document_created_by ON document (created_by);

ALTER TABLE document_line ADD FOREIGN KEY (document_id) REFERENCES document(id) ON DELETE RESTRICT;

CREATE INDEX ix_document_line_document_id ON document_line (document_id);

ALTER TABLE document_line ADD FOREIGN KEY (product_id) REFERENCES product(id) ON DELETE RESTRICT;

CREATE INDEX ix_document_line_product_id ON document_line (product_id);

ALTER TABLE document_line ADD FOREIGN KEY (uom_id) REFERENCES uom(id) ON DELETE RESTRICT;

CREATE INDEX ix_document_line_uom_id ON document_line (uom_id);

ALTER TABLE document_line ADD FOREIGN KEY (source_line_id) REFERENCES document_line(id) ON DELETE RESTRICT;

CREATE INDEX ix_document_line_source_line_id ON document_line (source_line_id);

ALTER TABLE document_link ADD FOREIGN KEY (document_id) REFERENCES document(id) ON DELETE RESTRICT;

CREATE INDEX ix_document_link_document_id ON document_link (document_id);

ALTER TABLE document_link ADD FOREIGN KEY (related_document_id) REFERENCES document(id) ON DELETE RESTRICT;

CREATE INDEX ix_document_link_related_document_id ON document_link (related_document_id);

ALTER TABLE document_assignment ADD FOREIGN KEY (document_id) REFERENCES document(id) ON DELETE RESTRICT;

CREATE INDEX ix_document_assignment_document_id ON document_assignment (document_id);

ALTER TABLE document_assignment ADD FOREIGN KEY (user_id) REFERENCES app_user(id) ON DELETE RESTRICT;

CREATE INDEX ix_document_assignment_user_id ON document_assignment (user_id);

ALTER TABLE document_assignment ADD FOREIGN KEY (assigned_by) REFERENCES app_user(id) ON DELETE RESTRICT;

CREATE INDEX ix_document_assignment_assigned_by ON document_assignment (assigned_by);

ALTER TABLE inventory_transaction ADD FOREIGN KEY (document_id) REFERENCES document(id) ON DELETE RESTRICT;

CREATE INDEX ix_inventory_transaction_document_id ON inventory_transaction (document_id);

ALTER TABLE inventory_transaction ADD FOREIGN KEY (posted_by) REFERENCES app_user(id) ON DELETE RESTRICT;

CREATE INDEX ix_inventory_transaction_posted_by ON inventory_transaction (posted_by);

ALTER TABLE inventory_transaction ADD FOREIGN KEY (reverses_transaction_id) REFERENCES inventory_transaction(id) ON DELETE RESTRICT;

CREATE INDEX ix_inventory_transaction_reverses_transaction_id ON inventory_transaction (reverses_transaction_id);

ALTER TABLE stock_move ADD FOREIGN KEY (transaction_id) REFERENCES inventory_transaction(id) ON DELETE RESTRICT;

CREATE INDEX ix_stock_move_transaction_id ON stock_move (transaction_id);

ALTER TABLE stock_move ADD FOREIGN KEY (line_id) REFERENCES document_line(id) ON DELETE RESTRICT;

CREATE INDEX ix_stock_move_line_id ON stock_move (line_id);

ALTER TABLE stock_move ADD FOREIGN KEY (stock_item_id) REFERENCES stock_item(id) ON DELETE RESTRICT;

CREATE INDEX ix_stock_move_stock_item_id ON stock_move (stock_item_id);

ALTER TABLE stock_move ADD FOREIGN KEY (source_location_id) REFERENCES location(id) ON DELETE RESTRICT;

CREATE INDEX ix_stock_move_source_location_id ON stock_move (source_location_id);

ALTER TABLE stock_move ADD FOREIGN KEY (destination_location_id) REFERENCES location(id) ON DELETE RESTRICT;

CREATE INDEX ix_stock_move_destination_location_id ON stock_move (destination_location_id);

ALTER TABLE stock_move ADD FOREIGN KEY (base_uom_id) REFERENCES uom(id) ON DELETE RESTRICT;

CREATE INDEX ix_stock_move_base_uom_id ON stock_move (base_uom_id);

ALTER TABLE stock_move ADD FOREIGN KEY (reverses_move_id) REFERENCES stock_move(id) ON DELETE RESTRICT;

CREATE INDEX ix_stock_move_reverses_move_id ON stock_move (reverses_move_id);

ALTER TABLE stock_balance ADD FOREIGN KEY (stock_item_id) REFERENCES stock_item(id) ON DELETE RESTRICT;

CREATE INDEX ix_stock_balance_stock_item_id ON stock_balance (stock_item_id);

ALTER TABLE stock_balance ADD FOREIGN KEY (location_id) REFERENCES location(id) ON DELETE RESTRICT;

CREATE INDEX ix_stock_balance_location_id ON stock_balance (location_id);

ALTER TABLE serial_position ADD FOREIGN KEY (serial_id) REFERENCES serial(id) ON DELETE RESTRICT;

CREATE INDEX ix_serial_position_serial_id ON serial_position (serial_id);

ALTER TABLE serial_position ADD FOREIGN KEY (location_id) REFERENCES location(id) ON DELETE RESTRICT;

CREATE INDEX ix_serial_position_location_id ON serial_position (location_id);

ALTER TABLE serial_position ADD FOREIGN KEY (last_move_id) REFERENCES stock_move(id) ON DELETE RESTRICT;

CREATE INDEX ix_serial_position_last_move_id ON serial_position (last_move_id);

ALTER TABLE reservation ADD FOREIGN KEY (line_id) REFERENCES document_line(id) ON DELETE RESTRICT;

CREATE INDEX ix_reservation_line_id ON reservation (line_id);

ALTER TABLE reservation ADD FOREIGN KEY (stock_item_id) REFERENCES stock_item(id) ON DELETE RESTRICT;

CREATE INDEX ix_reservation_stock_item_id ON reservation (stock_item_id);

ALTER TABLE reservation ADD FOREIGN KEY (location_id) REFERENCES location(id) ON DELETE RESTRICT;

CREATE INDEX ix_reservation_location_id ON reservation (location_id);

ALTER TABLE reservation ADD FOREIGN KEY (created_by) REFERENCES app_user(id) ON DELETE RESTRICT;

CREATE INDEX ix_reservation_created_by ON reservation (created_by);

ALTER TABLE pick_task ADD FOREIGN KEY (reservation_id) REFERENCES reservation(id) ON DELETE RESTRICT;

CREATE INDEX ix_pick_task_reservation_id ON pick_task (reservation_id);

ALTER TABLE pick_task ADD FOREIGN KEY (assigned_to) REFERENCES app_user(id) ON DELETE RESTRICT;

CREATE INDEX ix_pick_task_assigned_to ON pick_task (assigned_to);

ALTER TABLE reservation_consumption ADD FOREIGN KEY (reservation_id) REFERENCES reservation(id) ON DELETE RESTRICT;

CREATE INDEX ix_reservation_consumption_reservation_id ON reservation_consumption (reservation_id);

ALTER TABLE reservation_consumption ADD FOREIGN KEY (move_id) REFERENCES stock_move(id) ON DELETE RESTRICT;

CREATE INDEX ix_reservation_consumption_move_id ON reservation_consumption (move_id);

ALTER TABLE package ADD FOREIGN KEY (document_id) REFERENCES document(id) ON DELETE RESTRICT;

CREATE INDEX ix_package_document_id ON package (document_id);

ALTER TABLE package_line ADD FOREIGN KEY (package_id) REFERENCES package(id) ON DELETE RESTRICT;

CREATE INDEX ix_package_line_package_id ON package_line (package_id);

ALTER TABLE package_line ADD FOREIGN KEY (document_line_id) REFERENCES document_line(id) ON DELETE RESTRICT;

CREATE INDEX ix_package_line_document_line_id ON package_line (document_line_id);

ALTER TABLE package_line ADD FOREIGN KEY (stock_item_id) REFERENCES stock_item(id) ON DELETE RESTRICT;

CREATE INDEX ix_package_line_stock_item_id ON package_line (stock_item_id);

ALTER TABLE quality_decision ADD FOREIGN KEY (receipt_move_id) REFERENCES stock_move(id) ON DELETE RESTRICT;

CREATE INDEX ix_quality_decision_receipt_move_id ON quality_decision (receipt_move_id);

ALTER TABLE quality_decision ADD FOREIGN KEY (decided_by) REFERENCES app_user(id) ON DELETE RESTRICT;

CREATE INDEX ix_quality_decision_decided_by ON quality_decision (decided_by);

ALTER TABLE quality_decision ADD FOREIGN KEY (followup_document_id) REFERENCES document(id) ON DELETE RESTRICT;

CREATE INDEX ix_quality_decision_followup_document_id ON quality_decision (followup_document_id);

ALTER TABLE approval_policy_step ADD FOREIGN KEY (policy_id) REFERENCES approval_policy(id) ON DELETE RESTRICT;

CREATE INDEX ix_approval_policy_step_policy_id ON approval_policy_step (policy_id);

ALTER TABLE approval_policy_step ADD FOREIGN KEY (role_id) REFERENCES role(id) ON DELETE RESTRICT;

CREATE INDEX ix_approval_policy_step_role_id ON approval_policy_step (role_id);

ALTER TABLE approval_request ADD FOREIGN KEY (document_id) REFERENCES document(id) ON DELETE RESTRICT;

CREATE INDEX ix_approval_request_document_id ON approval_request (document_id);

ALTER TABLE approval_request ADD FOREIGN KEY (policy_id) REFERENCES approval_policy(id) ON DELETE RESTRICT;

CREATE INDEX ix_approval_request_policy_id ON approval_request (policy_id);

ALTER TABLE approval_request ADD FOREIGN KEY (requested_by) REFERENCES app_user(id) ON DELETE RESTRICT;

CREATE INDEX ix_approval_request_requested_by ON approval_request (requested_by);

ALTER TABLE approval_step ADD FOREIGN KEY (request_id) REFERENCES approval_request(id) ON DELETE RESTRICT;

CREATE INDEX ix_approval_step_request_id ON approval_step (request_id);

ALTER TABLE approval_step ADD FOREIGN KEY (required_role_id) REFERENCES role(id) ON DELETE RESTRICT;

CREATE INDEX ix_approval_step_required_role_id ON approval_step (required_role_id);

ALTER TABLE approval_step ADD FOREIGN KEY (decided_by) REFERENCES app_user(id) ON DELETE RESTRICT;

CREATE INDEX ix_approval_step_decided_by ON approval_step (decided_by);

ALTER TABLE stock_period ADD FOREIGN KEY (warehouse_id) REFERENCES warehouse(id) ON DELETE RESTRICT;

CREATE INDEX ix_stock_period_warehouse_id ON stock_period (warehouse_id);

ALTER TABLE stock_period ADD FOREIGN KEY (closed_by) REFERENCES app_user(id) ON DELETE RESTRICT;

CREATE INDEX ix_stock_period_closed_by ON stock_period (closed_by);

ALTER TABLE count_session ADD FOREIGN KEY (warehouse_id) REFERENCES warehouse(id) ON DELETE RESTRICT;

CREATE INDEX ix_count_session_warehouse_id ON count_session (warehouse_id);

ALTER TABLE count_session ADD FOREIGN KEY (created_by) REFERENCES app_user(id) ON DELETE RESTRICT;

CREATE INDEX ix_count_session_created_by ON count_session (created_by);

ALTER TABLE count_session ADD FOREIGN KEY (adjustment_document_id) REFERENCES document(id) ON DELETE RESTRICT;

CREATE INDEX ix_count_session_adjustment_document_id ON count_session (adjustment_document_id);

ALTER TABLE count_location_lock ADD FOREIGN KEY (session_id) REFERENCES count_session(id) ON DELETE RESTRICT;

CREATE INDEX ix_count_location_lock_session_id ON count_location_lock (session_id);

ALTER TABLE count_location_lock ADD FOREIGN KEY (location_id) REFERENCES location(id) ON DELETE RESTRICT;

CREATE INDEX ix_count_location_lock_location_id ON count_location_lock (location_id);

ALTER TABLE count_assignment ADD FOREIGN KEY (session_id) REFERENCES count_session(id) ON DELETE RESTRICT;

CREATE INDEX ix_count_assignment_session_id ON count_assignment (session_id);

ALTER TABLE count_assignment ADD FOREIGN KEY (location_id) REFERENCES location(id) ON DELETE RESTRICT;

CREATE INDEX ix_count_assignment_location_id ON count_assignment (location_id);

ALTER TABLE count_assignment ADD FOREIGN KEY (user_id) REFERENCES app_user(id) ON DELETE RESTRICT;

CREATE INDEX ix_count_assignment_user_id ON count_assignment (user_id);

ALTER TABLE count_assignment ADD FOREIGN KEY (assigned_by) REFERENCES app_user(id) ON DELETE RESTRICT;

CREATE INDEX ix_count_assignment_assigned_by ON count_assignment (assigned_by);

ALTER TABLE count_line ADD FOREIGN KEY (session_id) REFERENCES count_session(id) ON DELETE RESTRICT;

CREATE INDEX ix_count_line_session_id ON count_line (session_id);

ALTER TABLE count_line ADD FOREIGN KEY (stock_item_id) REFERENCES stock_item(id) ON DELETE RESTRICT;

CREATE INDEX ix_count_line_stock_item_id ON count_line (stock_item_id);

ALTER TABLE count_line ADD FOREIGN KEY (location_id) REFERENCES location(id) ON DELETE RESTRICT;

CREATE INDEX ix_count_line_location_id ON count_line (location_id);

ALTER TABLE count_observation ADD FOREIGN KEY (count_line_id) REFERENCES count_line(id) ON DELETE RESTRICT;

CREATE INDEX ix_count_observation_count_line_id ON count_observation (count_line_id);

ALTER TABLE count_observation ADD FOREIGN KEY (counted_by) REFERENCES app_user(id) ON DELETE RESTRICT;

CREATE INDEX ix_count_observation_counted_by ON count_observation (counted_by);

ALTER TABLE idempotency_record ADD FOREIGN KEY (actor_id) REFERENCES app_user(id) ON DELETE RESTRICT;

CREATE INDEX ix_idempotency_record_actor_id ON idempotency_record (actor_id);

ALTER TABLE consumer_receipt ADD FOREIGN KEY (event_id) REFERENCES outbox_event(id) ON DELETE RESTRICT;

CREATE INDEX ix_consumer_receipt_event_id ON consumer_receipt (event_id);

ALTER TABLE audit_event ADD FOREIGN KEY (actor_id) REFERENCES app_user(id) ON DELETE RESTRICT;

CREATE INDEX ix_audit_event_actor_id ON audit_event (actor_id);

ALTER TABLE audit_event ADD FOREIGN KEY (warehouse_id) REFERENCES warehouse(id) ON DELETE RESTRICT;

CREATE INDEX ix_audit_event_warehouse_id ON audit_event (warehouse_id);

ALTER TABLE stored_file ADD FOREIGN KEY (uploaded_by) REFERENCES app_user(id) ON DELETE RESTRICT;

CREATE INDEX ix_stored_file_uploaded_by ON stored_file (uploaded_by);

ALTER TABLE document_attachment ADD FOREIGN KEY (document_id) REFERENCES document(id) ON DELETE RESTRICT;

CREATE INDEX ix_document_attachment_document_id ON document_attachment (document_id);

ALTER TABLE document_attachment ADD FOREIGN KEY (file_id) REFERENCES stored_file(id) ON DELETE RESTRICT;

CREATE INDEX ix_document_attachment_file_id ON document_attachment (file_id);

ALTER TABLE product_image ADD FOREIGN KEY (product_id) REFERENCES product(id) ON DELETE RESTRICT;

CREATE INDEX ix_product_image_product_id ON product_image (product_id);

ALTER TABLE product_image ADD FOREIGN KEY (file_id) REFERENCES stored_file(id) ON DELETE RESTRICT;

CREATE INDEX ix_product_image_file_id ON product_image (file_id);

ALTER TABLE import_job ADD FOREIGN KEY (file_id) REFERENCES stored_file(id) ON DELETE RESTRICT;

CREATE INDEX ix_import_job_file_id ON import_job (file_id);

ALTER TABLE import_job ADD FOREIGN KEY (requested_by) REFERENCES app_user(id) ON DELETE RESTRICT;

CREATE INDEX ix_import_job_requested_by ON import_job (requested_by);

ALTER TABLE import_row ADD FOREIGN KEY (job_id) REFERENCES import_job(id) ON DELETE RESTRICT;

CREATE INDEX ix_import_row_job_id ON import_row (job_id);

ALTER TABLE export_job ADD FOREIGN KEY (requested_by) REFERENCES app_user(id) ON DELETE RESTRICT;

CREATE INDEX ix_export_job_requested_by ON export_job (requested_by);

ALTER TABLE export_job ADD FOREIGN KEY (file_id) REFERENCES stored_file(id) ON DELETE RESTRICT;

CREATE INDEX ix_export_job_file_id ON export_job (file_id);

ALTER TABLE document ADD CHECK (kind = 'TRANSFER' OR (destination_warehouse_id IS NULL AND transit_location_id IS NULL));

CREATE UNIQUE INDEX uq_stock_item_dimensions ON stock_item (product_id,lot_id,serial_id) NULLS NOT DISTINCT;

CREATE UNIQUE INDEX uq_active_product_uom ON product_uom(product_id,uom_id) WHERE is_active;

CREATE UNIQUE INDEX uq_active_policy ON approval_policy(document_kind) WHERE is_active;

CREATE UNIQUE INDEX uq_active_location_lock ON count_location_lock(location_id) WHERE released_at IS NULL;

CREATE UNIQUE INDEX uq_transfer_transit ON document(transit_location_id) WHERE transit_location_id IS NOT NULL;

CREATE UNIQUE INDEX uq_reversed_transaction ON inventory_transaction(reverses_transaction_id) WHERE reverses_transaction_id IS NOT NULL;

CREATE UNIQUE INDEX uq_reversed_move ON stock_move(reverses_move_id) WHERE reverses_move_id IS NOT NULL;

CREATE UNIQUE INDEX uq_count_scan ON count_observation(scan_event_key) WHERE scan_event_key IS NOT NULL;

CREATE INDEX ix_transaction_date ON inventory_transaction(business_date,posted_at,id);

CREATE INDEX ix_document_queue ON document(warehouse_id,status,business_date,id);

CREATE INDEX ix_outbox_pending ON outbox_event(available_at,id) WHERE processed_at IS NULL;

CREATE INDEX ix_audit_time ON audit_event(warehouse_id,occurred_at,id);

CREATE INDEX ix_lot_expiry ON lot(expires_on) WHERE expires_on IS NOT NULL;

CREATE FUNCTION forbid_ledger_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'append-only relation: %', TG_TABLE_NAME; END; $$;

CREATE TRIGGER immutable_stock_move BEFORE UPDATE OR DELETE ON stock_move FOR EACH ROW EXECUTE FUNCTION forbid_ledger_mutation();

CREATE TRIGGER immutable_inventory_transaction BEFORE UPDATE OR DELETE ON inventory_transaction FOR EACH ROW EXECUTE FUNCTION forbid_ledger_mutation();

CREATE TRIGGER immutable_audit_event BEFORE UPDATE OR DELETE ON audit_event FOR EACH ROW EXECUTE FUNCTION forbid_ledger_mutation();

CREATE TRIGGER immutable_count_observation BEFORE UPDATE OR DELETE ON count_observation FOR EACH ROW EXECUTE FUNCTION forbid_ledger_mutation();

COMMIT;

-- Verified recovery channels and explicit Google linking; no default identities.
CREATE TABLE wms.auth_contact (
  user_id uuid NOT NULL REFERENCES wms.app_user(id),
  kind text NOT NULL CHECK (kind IN ('email','sms')),
  value text NOT NULL,
  verified_at timestamptz NOT NULL,
  PRIMARY KEY(user_id,kind), UNIQUE(kind,value)
);
CREATE TABLE wms.auth_contact_challenge (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES wms.app_user(id),
  kind text NOT NULL CHECK (kind IN ('email','sms')),
  value text NOT NULL,
  code_hash char(64) NOT NULL,
  auth_version integer NOT NULL,
  expires_at timestamptz NOT NULL,
  consumed_at timestamptz
);
CREATE TABLE wms.auth_self_reset (
  token_hash char(64) PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES wms.app_user(id),
  kind text NOT NULL,
  contact_value text NOT NULL,
  auth_version integer NOT NULL,
  expires_at timestamptz NOT NULL,
  consumed_at timestamptz
);
CREATE INDEX ix_auth_self_reset_user ON wms.auth_self_reset(user_id);
CREATE TABLE wms.auth_delivery (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES wms.app_user(id),
  auth_version integer NOT NULL,
  ciphertext text,
  expires_at timestamptz NOT NULL,
  attempts integer NOT NULL DEFAULT 0 CHECK(attempts>=0),
  lease_until timestamptz,
  lease_token uuid,
  completed_at timestamptz,
  last_error text CHECK(last_error IS NULL OR last_error='DELIVERY_FAILED')
);
CREATE INDEX ix_auth_delivery_pending ON wms.auth_delivery(expires_at) WHERE completed_at IS NULL;
CREATE TABLE wms.auth_google_identity (
  subject text PRIMARY KEY,
  user_id uuid NOT NULL UNIQUE REFERENCES wms.app_user(id),
  linked_at timestamptz NOT NULL
);
CREATE TABLE wms.auth_google_flow (
  state_hash char(64) PRIMARY KEY,
  nonce_hash char(64) NOT NULL,
  verifier_ciphertext text,
  redirect_uri text NOT NULL,
  device_id uuid NOT NULL,
  user_id uuid REFERENCES wms.app_user(id),
  session_id uuid REFERENCES wms.auth_session(id),
  auth_version integer,
  expires_at timestamptz NOT NULL,
  consumed_at timestamptz
);

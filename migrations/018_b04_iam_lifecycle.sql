-- Development revision B04. Release numbering is assigned by integration.
-- Only digests of high-entropy, one-time credentials are persisted.
CREATE TABLE wms.auth_recovery_code (
  code_hash char(64) PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES wms.app_user(id),
  created_at timestamptz NOT NULL,
  consumed_at timestamptz,
  revoked_at timestamptz
);
CREATE INDEX ix_auth_recovery_user ON wms.auth_recovery_code(user_id);

CREATE TABLE wms.auth_password_reset (
  token_hash char(64) PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES wms.app_user(id),
  issued_by uuid NOT NULL REFERENCES wms.app_user(id),
  auth_version integer NOT NULL,
  created_at timestamptz NOT NULL,
  expires_at timestamptz NOT NULL,
  consumed_at timestamptz,
  CHECK(expires_at > created_at),
  CHECK(user_id <> issued_by)
);
CREATE INDEX ix_auth_password_reset_user ON wms.auth_password_reset(user_id);

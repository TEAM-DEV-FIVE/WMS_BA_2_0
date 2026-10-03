-- Additive IAM schema; 001/002 remain immutable baseline snapshots.
ALTER TABLE wms.auth_session ADD COLUMN mfa_verified_at timestamptz;
ALTER TABLE wms.mfa_factor ADD COLUMN last_counter bigint NOT NULL DEFAULT -1;
ALTER TABLE wms.mfa_factor ADD COLUMN enrollment_expires_at timestamptz;
CREATE UNIQUE INDEX uq_verified_totp ON wms.mfa_factor(user_id)
  WHERE kind='TOTP' AND verified_at IS NOT NULL AND revoked_at IS NULL;

CREATE TABLE wms.auth_token (
  token_hash char(64) PRIMARY KEY,
  session_id uuid NOT NULL REFERENCES wms.auth_session(id) ON DELETE RESTRICT,
  kind varchar(10) NOT NULL CHECK(kind IN ('ACCESS','REFRESH')),
  created_at timestamptz NOT NULL,
  expires_at timestamptz NOT NULL,
  used_at timestamptz,
  CHECK(expires_at > created_at)
);
CREATE INDEX ix_auth_token_session ON wms.auth_token(session_id);

CREATE TABLE wms.auth_challenge (
  token_hash char(64) PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES wms.app_user(id) ON DELETE RESTRICT,
  device_id uuid NOT NULL,
  auth_version integer NOT NULL,
  expires_at timestamptz NOT NULL,
  consumed_at timestamptz
);
CREATE INDEX ix_auth_challenge_user ON wms.auth_challenge(user_id);

-- Separate password/MFA counters shared by all workers; keys are hashes, not usernames.
CREATE TABLE wms.auth_throttle (
  key char(64) PRIMARY KEY,
  failures integer NOT NULL CHECK(failures >= 0),
  window_started_at timestamptz NOT NULL,
  blocked_until timestamptz
);

-- IAM grant requests require a second authenticated administrator to approve.
CREATE TABLE wms.grant_request (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES wms.app_user(id),
  role_id uuid NOT NULL REFERENCES wms.role(id),
  scope_kind varchar(20) NOT NULL CHECK(scope_kind IN ('GLOBAL','WAREHOUSE','ALL_WAREHOUSES')),
  warehouse_id uuid REFERENCES wms.warehouse(id),
  valid_until timestamptz,
  reason text NOT NULL,
  requested_by uuid NOT NULL REFERENCES wms.app_user(id),
  requested_at timestamptz NOT NULL,
  approved_by uuid REFERENCES wms.app_user(id),
  grant_id uuid UNIQUE REFERENCES wms.user_role_grant(id),
  CHECK((scope_kind='WAREHOUSE') = (warehouse_id IS NOT NULL)),
  CHECK(requested_by <> user_id),
  CHECK(approved_by IS NULL OR (approved_by <> requested_by AND approved_by <> user_id)),
  CHECK((approved_by IS NULL) = (grant_id IS NULL))
);

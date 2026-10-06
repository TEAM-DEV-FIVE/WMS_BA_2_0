-- Development B17 revision. Immutable, bounded snapshots and a DB-only queue.
CREATE TABLE wms.report_request_guard (
  user_id uuid PRIMARY KEY REFERENCES wms.app_user(id),
  version bigint NOT NULL DEFAULT 1 CHECK (version>0)
);
CREATE TABLE wms.report_snapshot (
  id uuid PRIMARY KEY,
  requested_by uuid NOT NULL REFERENCES wms.app_user(id),
  report_code varchar(3) NOT NULL CHECK (report_code IN ('R01','R02','R03','R04','R05','R06','R07','R08')),
  criteria jsonb NOT NULL,
  required_warehouses uuid[] NOT NULL,
  created_at timestamptz NOT NULL,
  expires_at timestamptz NOT NULL CHECK (expires_at>created_at),
  row_count integer NOT NULL CHECK (row_count BETWEEN 0 AND 20000),
  columns jsonb NOT NULL,
  sha256 char(64) NOT NULL,
  CHECK (jsonb_typeof(criteria)='object' AND jsonb_typeof(columns)='array')
);
CREATE INDEX ix_report_snapshot_actor ON wms.report_snapshot(requested_by,expires_at);
CREATE TABLE wms.report_snapshot_row (
  snapshot_id uuid NOT NULL REFERENCES wms.report_snapshot(id) ON DELETE CASCADE,
  ordinal integer NOT NULL CHECK (ordinal BETWEEN 1 AND 20000),
  payload jsonb NOT NULL CHECK (jsonb_typeof(payload)='object'),
  PRIMARY KEY(snapshot_id,ordinal)
);
CREATE TRIGGER immutable_report_snapshot BEFORE UPDATE ON wms.report_snapshot
FOR EACH ROW EXECUTE FUNCTION wms.forbid_ledger_mutation();
CREATE TRIGGER immutable_report_row BEFORE UPDATE ON wms.report_snapshot_row
FOR EACH ROW EXECUTE FUNCTION wms.forbid_ledger_mutation();

-- Preserve legacy rows; only jobs with snapshot_id are exposed by B17.
ALTER TABLE wms.export_job
  ADD COLUMN snapshot_id uuid REFERENCES wms.report_snapshot(id),
  ADD COLUMN session_id uuid REFERENCES wms.auth_session(id),
  ADD COLUMN format varchar(4) CHECK (format IN ('csv','xlsx')),
  ADD COLUMN version integer NOT NULL DEFAULT 1 CHECK (version>0),
  ADD COLUMN generation integer NOT NULL DEFAULT 1 CHECK (generation>0),
  ADD COLUMN error_code varchar(40),
  ADD CONSTRAINT export_snapshot_state CHECK (snapshot_id IS NULL OR
    (session_id IS NOT NULL AND format IS NOT NULL AND expires_at IS NOT NULL
     AND status IN ('QUEUED','RUNNING','READY','FAILED','CANCELLED')));
CREATE INDEX ix_export_actor ON wms.export_job(requested_by,expires_at);
CREATE UNIQUE INDEX uq_export_snapshot_format ON wms.export_job(snapshot_id,format) WHERE snapshot_id IS NOT NULL;
CREATE TABLE wms.export_task (
  id uuid PRIMARY KEY,
  job_id uuid NOT NULL REFERENCES wms.export_job(id),
  generation integer NOT NULL CHECK (generation>0),
  status varchar(10) NOT NULL DEFAULT 'READY' CHECK (status IN ('READY','RUNNING','DONE','EXHAUSTED')),
  attempts integer NOT NULL DEFAULT 0 CHECK (attempts>=0),
  available_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  lease_token uuid,
  lease_until timestamptz,
  UNIQUE(job_id,generation)
);
CREATE INDEX ix_export_task_queue ON wms.export_task(available_at,id) WHERE status IN ('READY','RUNNING');

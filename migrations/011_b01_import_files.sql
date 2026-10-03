CREATE TABLE wms.import_file (
  file_id uuid PRIMARY KEY REFERENCES wms.stored_file(id),
  actor_id uuid NOT NULL REFERENCES wms.app_user(id),
  warehouse_id uuid REFERENCES wms.warehouse(id),
  kind varchar(60) NOT NULL,
  upload_key uuid NOT NULL,
  request_hash char(64) NOT NULL,
  ready boolean NOT NULL DEFAULT false,
  UNIQUE(actor_id,upload_key)
);
CREATE INDEX ix_import_file_warehouse ON wms.import_file(warehouse_id);

ALTER TABLE wms.import_job ADD COLUMN warehouse_id uuid REFERENCES wms.warehouse(id);
ALTER TABLE wms.import_job ADD COLUMN version integer NOT NULL DEFAULT 1 CHECK (version>0);
ALTER TABLE wms.import_job ADD COLUMN generation integer NOT NULL DEFAULT 1 CHECK (generation>0);
ALTER TABLE wms.import_job ADD COLUMN auth_version integer;
ALTER TABLE wms.import_job ADD COLUMN options jsonb NOT NULL DEFAULT '{}';
ALTER TABLE wms.import_job ADD COLUMN commit_token uuid;
ALTER TABLE wms.import_job ADD COLUMN token_expires_at timestamptz;
ALTER TABLE wms.import_job ADD COLUMN stage_hash char(64);
ALTER TABLE wms.import_job ADD COLUMN data_snapshot jsonb NOT NULL DEFAULT '[]';
ALTER TABLE wms.import_job ADD COLUMN total_rows integer NOT NULL DEFAULT 0 CHECK (total_rows>=0);
ALTER TABLE wms.import_job ADD COLUMN processed_rows integer NOT NULL DEFAULT 0 CHECK (processed_rows>=0);
ALTER TABLE wms.import_job ADD COLUMN errors jsonb NOT NULL DEFAULT '[]';
ALTER TABLE wms.import_job ADD COLUMN result jsonb;
CREATE INDEX ix_import_job_warehouse ON wms.import_job(warehouse_id);
-- Legacy jobs lack auth_version and are never silently reactivated or deduplicated as verified jobs.
CREATE UNIQUE INDEX uq_import_content ON wms.import_job(requested_by,kind,warehouse_id,file_hash)
  NULLS NOT DISTINCT WHERE auth_version IS NOT NULL;

CREATE TABLE wms.import_task (
  id uuid PRIMARY KEY,
  job_id uuid NOT NULL REFERENCES wms.import_job(id),
  generation integer NOT NULL CHECK (generation>0),
  state varchar(20) NOT NULL CHECK (state IN ('READY','RUNNING','DONE','EXHAUSTED')),
  lease_token uuid,
  lease_until timestamptz,
  attempts integer NOT NULL DEFAULT 0 CHECK (attempts>=0),
  available_at timestamptz NOT NULL,
  last_error varchar(60),
  UNIQUE(job_id,generation)
);
CREATE INDEX ix_import_task_due ON wms.import_task(available_at,id) WHERE state IN ('READY','RUNNING');

CREATE TABLE wms.import_document_source (
  warehouse_id uuid NOT NULL REFERENCES wms.warehouse(id),
  kind varchar(20) NOT NULL CHECK (kind IN ('PO','SO','OPENING')),
  source_key varchar(240) NOT NULL,
  document_id uuid NOT NULL UNIQUE REFERENCES wms.document(id),
  job_id uuid NOT NULL REFERENCES wms.import_job(id),
  PRIMARY KEY(warehouse_id,kind,source_key)
);
CREATE INDEX ix_import_document_source_job ON wms.import_document_source(job_id);

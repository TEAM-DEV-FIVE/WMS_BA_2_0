-- B18 development revision. Inventory ledger is deliberately untouched.
CREATE TABLE wms.print_job (
 id uuid PRIMARY KEY,
 requested_by uuid NOT NULL REFERENCES wms.app_user(id),
 session_id uuid NOT NULL REFERENCES wms.auth_session(id),
 warehouse_id uuid NOT NULL REFERENCES wms.warehouse(id),
 source_id uuid NOT NULL,
 source_version integer NOT NULL CHECK(source_version>0),
 template varchar(20) NOT NULL CHECK(template IN ('RECEIPT','ISSUE','TRANSFER','COUNT','PRODUCT_LABEL','LOCATION_LABEL')),
 template_version integer NOT NULL DEFAULT 1 CHECK(template_version=1),
 paper varchar(10) NOT NULL CHECK(paper IN ('A4','A5','100x50','80x40')),
 include_price boolean NOT NULL,
 criteria jsonb NOT NULL,
 snapshot jsonb NOT NULL,
 snapshot_hash char(64) NOT NULL,
 status varchar(12) NOT NULL DEFAULT 'QUEUED' CHECK(status IN ('QUEUED','RENDERING','READY','FAILED','CANCELLED')),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 generation integer NOT NULL DEFAULT 1 CHECK(generation>0),
 file_id uuid REFERENCES wms.stored_file(id),
 created_at timestamptz NOT NULL,
 expires_at timestamptz NOT NULL,
 error_code varchar(40),
 CHECK(expires_at>created_at)
);
CREATE INDEX ix_print_job_actor ON wms.print_job(requested_by,expires_at);
CREATE TABLE wms.print_task (
 id uuid PRIMARY KEY,
 job_id uuid NOT NULL REFERENCES wms.print_job(id),
 generation integer NOT NULL CHECK(generation>0),
 status varchar(10) NOT NULL DEFAULT 'READY' CHECK(status IN ('READY','RUNNING','DONE','EXHAUSTED')),
 attempts integer NOT NULL DEFAULT 0 CHECK(attempts>=0),
 available_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 lease_token uuid,
 lease_until timestamptz,
 UNIQUE(job_id,generation)
);
CREATE TABLE wms.print_attempt (
 id uuid PRIMARY KEY,
 job_id uuid NOT NULL REFERENCES wms.print_job(id),
 generation integer NOT NULL CHECK(generation>0),
 actor_id uuid NOT NULL REFERENCES wms.app_user(id),
 session_id uuid NOT NULL REFERENCES wms.auth_session(id),
 printer varchar(200) NOT NULL,
 driver varchar(20) NOT NULL CHECK(driver IN ('WINDOWS_GDI','CUPS')),
 copies integer NOT NULL CHECK(copies BETWEEN 1 AND 20),
 status varchar(10) NOT NULL DEFAULT 'UNKNOWN' CHECK(status IN ('UNKNOWN','SUBMITTED','FAILED')),
 spool_id varchar(200),
 error_code varchar(40),
 created_at timestamptz NOT NULL,
 finished_at timestamptz,
 UNIQUE(job_id,generation)
);
CREATE FUNCTION wms.protect_print_snapshot() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (NEW.requested_by,NEW.warehouse_id,NEW.source_id,NEW.source_version,NEW.template,
     NEW.template_version,NEW.paper,NEW.include_price,NEW.criteria,NEW.snapshot,NEW.snapshot_hash,
     NEW.created_at,NEW.expires_at) IS DISTINCT FROM
    (OLD.requested_by,OLD.warehouse_id,OLD.source_id,OLD.source_version,OLD.template,
     OLD.template_version,OLD.paper,OLD.include_price,OLD.criteria,OLD.snapshot,OLD.snapshot_hash,
     OLD.created_at,OLD.expires_at) THEN
   RAISE EXCEPTION 'Print snapshots are immutable' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER print_snapshot_immutable BEFORE UPDATE ON wms.print_job
 FOR EACH ROW EXECUTE FUNCTION wms.protect_print_snapshot();

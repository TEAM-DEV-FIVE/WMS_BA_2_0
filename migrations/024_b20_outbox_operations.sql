-- Development revision; coordinator assigns the next release number.
ALTER TABLE wms.outbox_event
 ADD COLUMN version integer NOT NULL DEFAULT 1 CHECK(version>0),
 ADD COLUMN replay_count integer NOT NULL DEFAULT 0 CHECK(replay_count BETWEEN 0 AND 3),
 ADD COLUMN replayed_at timestamptz;

CREATE TABLE wms.worker_status (
 id uuid PRIMARY KEY,
 kind varchar(20) NOT NULL CHECK(kind IN ('outbox','import','export','print','export-cleanup','print-cleanup')),
 registry_hash char(64) NOT NULL,
 state varchar(10) NOT NULL CHECK(state IN ('STARTING','IDLE','BUSY','STOPPED','FAILED')),
 started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 heartbeat_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 result_code varchar(40),
 completed_cycles bigint NOT NULL DEFAULT 0 CHECK(completed_cycles>=0)
);
CREATE INDEX ix_worker_status_heartbeat ON wms.worker_status(heartbeat_at);

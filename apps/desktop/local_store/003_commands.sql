-- Legacy drafts/scan events/receipt operations remain untouched.
CREATE TABLE IF NOT EXISTS recovery_command (
 key TEXT PRIMARY KEY, schema_version INTEGER NOT NULL CHECK(schema_version=1),
 warehouse_id TEXT NOT NULL, envelope TEXT NOT NULL, payload_hash TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('DRAFT','READY','SENDING','UNKNOWN','COMMITTED','CONFLICT')),
 response TEXT, response_hash TEXT, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_recovery_scope ON recovery_command(warehouse_id,state,updated_at,key);

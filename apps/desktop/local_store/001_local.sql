-- SQLite CỤC BỘ, không đặt file DB trên network share. Một storage worker sở hữu connection.
PRAGMA foreign_keys = ON;
CREATE TABLE local_draft (id TEXT PRIMARY KEY, server_id TEXT NOT NULL, user_id TEXT NOT NULL, device_id TEXT NOT NULL,
 kind TEXT NOT NULL, server_document_id TEXT, server_version INTEGER, payload TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('LOCAL_DRAFT','READY','SYNCED','CONFLICT')), updated_at TEXT NOT NULL);
CREATE TABLE scan_event (id TEXT PRIMARY KEY, draft_id TEXT NOT NULL REFERENCES local_draft(id), barcode TEXT NOT NULL,
 quantity TEXT NOT NULL, occurred_at TEXT NOT NULL, synced_at TEXT);
CREATE TABLE pending_operation (key TEXT PRIMARY KEY, draft_id TEXT REFERENCES local_draft(id), execution_key TEXT NOT NULL,
 server_id TEXT NOT NULL, user_id TEXT NOT NULL, endpoint TEXT NOT NULL, payload TEXT NOT NULL, payload_hash TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('READY','SENDING','UNKNOWN','COMMITTED','CONFLICT')), response TEXT, updated_at TEXT NOT NULL);
CREATE TABLE cache_metadata (server_id TEXT NOT NULL, user_id TEXT NOT NULL, cache_key TEXT NOT NULL, fetched_at TEXT NOT NULL,
 payload TEXT NOT NULL, PRIMARY KEY(server_id,user_id,cache_key));
-- Không lưu password/token. Persist operation key + payload trước network send.
-- SENDING khi restart chuyển UNKNOWN, query server trước; retry cùng key. READY chỉ gửi post sau xác nhận online.

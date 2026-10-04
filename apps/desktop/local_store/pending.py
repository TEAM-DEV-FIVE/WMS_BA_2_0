# apps/desktop/local_store/pending.py
# Lưu thao tác đang gửi vào SQLite trên máy (không lưu password/token).
import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime


class PendingStore:
    def __init__(self):
        folder = os.path.join(os.path.expanduser("~"), ".wms_desktop")
        os.makedirs(folder, exist_ok=True)
        self.conn = sqlite3.connect(os.path.join(folder, "local.db"))
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS pending_operation (
                key TEXT PRIMARY KEY, draft_id TEXT, execution_key TEXT NOT NULL,
                server_id TEXT NOT NULL, user_id TEXT NOT NULL, endpoint TEXT NOT NULL,
                payload TEXT NOT NULL, payload_hash TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN
                    ('READY','SENDING','UNKNOWN','COMMITTED','CONFLICT')),
                response TEXT, updated_at TEXT NOT NULL)""")
        self.conn.commit()

    def save_pending(self, key, server_id, user_id, endpoint, payload):
        text = json.dumps(payload, sort_keys=True)
        self.conn.execute(
            "INSERT INTO pending_operation VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (key, None, payload.get("execution_key", str(uuid.uuid4())),
             server_id, user_id, endpoint, text,
             hashlib.sha256(text.encode("utf-8")).hexdigest(),
             "SENDING", None, datetime.now().isoformat()))
        self.conn.commit()

    def set_state(self, key, state, response=None):
        self.conn.execute(
            "UPDATE pending_operation SET state=?, response=?, updated_at=? WHERE key=?",
            (state, json.dumps(response) if response else None,
             datetime.now().isoformat(), key))
        self.conn.commit()

    def get_operation(self, key):
        row = self.conn.execute(
            "SELECT endpoint, payload FROM pending_operation WHERE key=?",
            (key,)).fetchone()
        return row[0], json.loads(row[1])

    def mark_sending_as_unknown(self):
        # App tắt giữa chừng: SENDING -> UNKNOWN (chưa biết server commit chưa)
        self.conn.execute(
            "UPDATE pending_operation SET state='UNKNOWN' WHERE state='SENDING'")
        self.conn.commit()

    def last_unknown_key(self):
        row = self.conn.execute(
            "SELECT key FROM pending_operation WHERE state='UNKNOWN' "
            "ORDER BY updated_at DESC LIMIT 1").fetchone()
        return row[0] if row else None
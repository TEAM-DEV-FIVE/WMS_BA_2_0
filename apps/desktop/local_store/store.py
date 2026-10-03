"""Single-worker SQLite storage; never stores credentials or auto-sends commands."""

import hashlib
import hmac
import json
import sqlite3
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from uuid import UUID, uuid4

from apps.desktop.local_store.device import PartitionLock, private_file

FORBIDDEN_FIELDS = {"password", "password_hash", "access_token", "refresh_token", "authorization", "secret"}
TRANSITIONS = {
    "READY": {"SENDING"},
    "SENDING": {"UNKNOWN", "COMMITTED", "CONFLICT"},
    "UNKNOWN": {"SENDING", "COMMITTED", "CONFLICT"},
    "COMMITTED": set(),
    "CONFLICT": set(),
}


def canonical_payload(payload: dict) -> str:
    def check(value):
        if isinstance(value, dict):
            if any(key.lower() in FORBIDDEN_FIELDS for key in value):
                raise ValueError("Credentials must not be stored in local drafts")
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)

    check(payload)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


class LocalStore:
    def __init__(self, directory: Path, *, server_id: str, user_id: UUID, device_id: UUID):
        self.server_id, self.user_id, self.device_id = server_id.rstrip("/"), str(user_id), str(device_id)
        partition = json.dumps([self.server_id, self.user_id, self.device_id]).encode()
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = directory / (hashlib.sha256(partition).hexdigest() + ".sqlite3")
        self.lock = PartitionLock(self.path.with_suffix(".lock"))
        self.connection = None
        try:
            private_file(self.path)
            self.connection = sqlite3.connect(self.path, timeout=2)
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA foreign_keys = ON")
            self.connection.execute("PRAGMA synchronous=FULL")
            version = self.connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in {0, 1, 2}:
                raise ValueError(
                    "Local store version is not supported; retain the file and use a compatible client"
                )
            revisions = ["001_local.sql", "002_recovery.sql"]
            sql = "\n".join(
                files("apps.desktop.local_store").joinpath(name).read_text(encoding="utf-8")
                for name in revisions[version:]
            )
            if sql:
                self.connection.executescript("BEGIN;\n" + sql + "\nPRAGMA user_version=2;\nCOMMIT;")
            with self.connection:
                self.connection.execute("UPDATE pending_operation SET state='UNKNOWN' WHERE state='SENDING'")
        except Exception:
            self.close()
            raise

    def save_draft(self, kind: str, payload: dict, draft_id: UUID | None = None) -> UUID:
        draft_id = draft_id or uuid4()
        encoded = canonical_payload(payload)
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO local_draft(id,server_id,user_id,device_id,kind,payload,state,updated_at)
                VALUES (?,?,?,?,?,?,'LOCAL_DRAFT',?)
                ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at
            """,
                (str(draft_id), self.server_id, self.user_id, self.device_id, kind, encoded, self.now()),
            )
        return draft_id

    def get_draft(self, draft_id: UUID) -> dict | None:
        row = self.connection.execute("SELECT * FROM local_draft WHERE id=?", (str(draft_id),)).fetchone()
        return dict(row) if row else None

    def prepare(
        self,
        *,
        key: UUID,
        execution_key: UUID,
        endpoint: str,
        payload: dict,
        draft_id: UUID | None = None,
        context: dict | None = None,
    ) -> None:
        encoded = canonical_payload(payload)
        digest = hashlib.sha256(json.dumps([endpoint, str(execution_key), encoded]).encode()).hexdigest()
        with self.connection:
            existing = self.operation(key)
            if existing:
                if existing["payload_hash"] != digest or existing["draft_id"] != (
                    str(draft_id) if draft_id else None
                ):
                    raise ValueError("Operation key cannot be reused with a different request")
                return
            self.connection.execute(
                """
                INSERT INTO pending_operation
                  (key,draft_id,execution_key,server_id,user_id,endpoint,payload,payload_hash,state,updated_at,context)
                VALUES (?,?,?,?,?,?,?,?,'READY',?,?)
            """,
                (
                    str(key),
                    str(draft_id) if draft_id else None,
                    str(execution_key),
                    self.server_id,
                    self.user_id,
                    endpoint,
                    encoded,
                    digest,
                    self.now(),
                    canonical_payload(context or {}),
                ),
            )

    def operation(self, key: UUID) -> dict | None:
        row = self.connection.execute(
            "SELECT * FROM pending_operation WHERE key=? AND server_id=? AND user_id=?",
            (str(key), self.server_id, self.user_id),
        ).fetchone()
        return dict(row) if row else None

    def operations(self, *, unresolved_only=False, limit=200):
        condition = " AND state IN ('READY','SENDING','UNKNOWN')" if unresolved_only else ""
        rows = self.connection.execute(
            "SELECT * FROM pending_operation WHERE server_id=? AND user_id=?"
            + condition
            + " ORDER BY CASE WHEN state IN ('READY','SENDING','UNKNOWN') THEN 0 ELSE 1 END, updated_at DESC, key LIMIT ?",
            (self.server_id, self.user_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def verify(self, key):
        record = self.operation(key)
        if record is None:
            raise ValueError("Unknown local operation")
        payload = json.loads(record["payload"])
        encoded = canonical_payload(payload)
        digest = hashlib.sha256(
            json.dumps([record["endpoint"], record["execution_key"], encoded]).encode()
        ).hexdigest()
        if not hmac.compare_digest(record["payload_hash"], digest):
            raise ValueError("Local operation hash mismatch; retain file for investigation")
        return record, payload

    def transition(self, key: UUID, state: str, *, response: dict | None = None) -> None:
        record = self.operation(key)
        if not record or state not in TRANSITIONS[record["state"]]:
            raise ValueError("Invalid pending operation transition")
        if state == "COMMITTED" and response is None:
            raise ValueError("Server confirmation is required before marking COMMITTED")
        encoded = canonical_payload(response) if response is not None else None
        with self.connection:
            self.connection.execute(
                "UPDATE pending_operation SET state=?,response=?,updated_at=? WHERE key=?",
                (state, encoded, self.now(), str(key)),
            )

    @staticmethod
    def now() -> str:
        return datetime.now(UTC).isoformat()

    def close(self) -> None:
        try:
            if self.connection is not None:
                self.connection.close()
                self.connection = None
        finally:
            self.lock.close()

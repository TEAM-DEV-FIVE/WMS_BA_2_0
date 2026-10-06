"""Immutable command envelopes, owned exclusively by the storage worker."""

import hmac
import json
from uuid import UUID

from apps.desktop.local_store.store import LocalStore, canonical_payload
from packages.contracts.recovery import digest, route_policy

TRANSITIONS = {
    "DRAFT": {"READY"}, "READY": {"SENDING"}, "SENDING": {"UNKNOWN", "COMMITTED", "CONFLICT"},
    "UNKNOWN": {"SENDING", "COMMITTED"}, "COMMITTED": set(), "CONFLICT": set(),
}


class CommandStore(LocalStore):
    def checked(self, key):
        row = self.connection.execute("SELECT * FROM recovery_command WHERE key=?", (str(key),)).fetchone()
        if row is None:
            return None
        record = dict(row)
        envelope = json.loads(record["envelope"])
        if (record["schema_version"] != 1 or envelope.get("version") != 1
                or envelope.get("server") != self.server_id or envelope.get("user") != self.user_id
                or envelope.get("device") != self.device_id or envelope.get("warehouse") != record["warehouse_id"]
                or envelope.get("key") != str(key)
                or not hmac.compare_digest(digest(envelope), record["payload_hash"])):
            raise ValueError("Recovery envelope hash/partition/schema mismatch; retain file")
        canonical_payload(envelope)
        if route_policy(envelope["method"], envelope["path"])[0] != "COMMAND":
            raise ValueError("Operation is not replayable")
        if record["response"] is not None:
            result = json.loads(record["response"])
            if not hmac.compare_digest(digest(result), record["response_hash"] or ""):
                raise ValueError("Recovery acknowledgement hash mismatch")
            record["response"] = result
        elif record["state"] in {"COMMITTED", "CONFLICT"}:
            raise ValueError("Missing recovery acknowledgement")
        record["envelope"] = envelope
        return record

    def prepare_command(self, method, path, body, key, warehouse="GLOBAL", *, draft=False):
        key = str(UUID(str(key)))
        if route_policy(method, path)[0] != "COMMAND" or not isinstance(body, dict):
            raise ValueError("Only classified JSON commands can be saved")
        if warehouse != "GLOBAL":
            warehouse = str(UUID(str(warehouse)))
        envelope = dict(version=1, server=self.server_id, user=self.user_id, device=self.device_id,
                        warehouse=warehouse, key=key, method=method, path=path, body=body)
        encoded = canonical_payload(envelope)
        if len(encoded.encode("utf-8")) > 2 * 1024 * 1024:
            raise ValueError("Recovery payload exceeds 2 MiB")
        existing = self.checked(key)
        if existing:
            if existing["payload_hash"] != digest(envelope):
                raise ValueError("Operation key cannot be reused with another payload/scope")
            return existing
        # Re-saving a never-sent draft updates that draft; frozen requests cannot change.
        for row in self.connection.execute("SELECT key FROM recovery_command WHERE state IN ('DRAFT','READY','SENDING','UNKNOWN')"):
            pending = self.checked(row[0])
            if pending["envelope"]["path"] == path:
                if draft and pending["state"] == "DRAFT" and pending["warehouse_id"] == warehouse:
                    envelope["key"] = pending["key"]
                    encoded = canonical_payload(envelope)
                    with self.connection:
                        self.connection.execute("UPDATE recovery_command SET envelope=?,payload_hash=?,updated_at=? WHERE key=?",
                                                (encoded, digest(envelope), self.now(), pending["key"]))
                    return self.checked(pending["key"])
                raise ValueError("Còn lệnh cùng thao tác chưa rõ kết quả. Mở Phục hồi lệnh trước khi tạo key mới.")
        with self.connection:
            self.connection.execute("""INSERT INTO recovery_command
                (key,schema_version,warehouse_id,envelope,payload_hash,state,updated_at) VALUES (?,1,?,?,?,?,?)""",
                (key, warehouse, encoded, digest(envelope), "DRAFT" if draft else "READY", self.now()))
        return self.checked(key)

    def discard_draft(self, key):
        record = self.checked(key)
        if not record or record["state"] != "DRAFT":
            raise ValueError("Only a never-sent draft can be discarded")
        with self.connection:
            self.connection.execute("DELETE FROM recovery_command WHERE key=? AND state='DRAFT'", (str(key),))

    def edit_draft(self, key, body):
        record = self.checked(key)
        if not record or record["state"] != "DRAFT" or not isinstance(body, dict):
            raise ValueError("Only a never-sent draft can be edited")
        envelope = {**record["envelope"], "body": body}
        encoded = canonical_payload(envelope)
        if len(encoded.encode("utf-8")) > 2 * 1024 * 1024:
            raise ValueError("Draft too large")
        # Scope, versions and execution identities are frozen even while editing a draft.
        def identities(value, path=()):
            result = {}
            if isinstance(value, dict):
                for field, child in value.items():
                    if field.endswith(("_id", "_version", "_key")) or field == "id":
                        result[path + (field,)] = child
                    else:
                        result.update(identities(child, path + (field,)))
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    result.update(identities(child, path + (index,)))
            return result
        if identities(body) != identities(record["envelope"]["body"]):
            raise ValueError("Refresh the business form to change references or version")
        with self.connection:
            self.connection.execute("UPDATE recovery_command SET envelope=?,payload_hash=?,updated_at=? WHERE key=?",
                                    (encoded, digest(envelope), self.now(), str(key)))

    def command_transition(self, key, state, response=None):
        record = self.checked(key)
        if not record or state not in TRANSITIONS[record["state"]]:
            raise ValueError("Invalid recovery transition")
        if state in {"COMMITTED", "CONFLICT"} and not isinstance(response, dict):
            raise ValueError("Server acknowledgement required")
        encoded = canonical_payload(response) if response is not None else None
        with self.connection:
            self.connection.execute("UPDATE recovery_command SET state=?,response=?,response_hash=?,updated_at=? WHERE key=?",
                                    (state, encoded, digest(response) if response is not None else None, self.now(), str(key)))

    def command_list(self, warehouse=None):
        rows = self.connection.execute("""SELECT key FROM recovery_command
            WHERE (? IS NULL OR warehouse_id=?) ORDER BY
            CASE WHEN state IN ('SENDING','UNKNOWN','READY','DRAFT') THEN 0 ELSE 1 END,updated_at DESC,key""",
            (warehouse, warehouse)).fetchall()
        return [self.checked(row[0]) for row in rows]

    def cleanup(self, before):
        # Explicit local housekeeping only; drafts and unresolved commands never expire.
        with self.connection:
            return self.connection.execute("DELETE FROM recovery_command WHERE state IN ('COMMITTED','CONFLICT') AND updated_at<?", (before,)).rowcount

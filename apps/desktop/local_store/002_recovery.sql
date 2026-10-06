-- UI display context only; command identity remains endpoint + execution key + payload.
ALTER TABLE pending_operation ADD COLUMN context TEXT NOT NULL DEFAULT '{}';
CREATE INDEX ix_pending_state_time ON pending_operation(state,updated_at,key);

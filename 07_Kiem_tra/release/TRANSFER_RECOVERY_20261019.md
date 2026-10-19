# Transfer draft recovery — 19/10/2026

Branch: `fix/transfer-same-warehouse-20261019`.
Base: `0f7073ef186f7ab7b3eb57005e9d458cddedd873`.

## Problem and changes

A POST transfers request with identical source/destination warehouses reached the
document SQL CHECK before domain validation. The transaction rolled back, but the
generic integrity error lacked a request-bound rejection acknowledgement. Desktop
retained UNKNOWN and blocked subsequent POST transfers requests. New transfer UI
also retained the previous document title and destination selection.

- Validate distinct warehouses inside the authorized command handler, before any
  INSERT or sequence allocation. Keep key locking, replay/hash checks and current
  permissions unchanged. Exact retry now returns INVALID_WAREHOUSE with the existing
  request-bound rejection header, allowing the journal to retain it as CONFLICT.
- Desktop validates distinct warehouses before preparing a command. New resets the
  document title, destination, stock selection, quantity, reason and evidence.
- No migrations, direct business-data updates, journal deletion or permission grants.

## Verification

- Disposable MySQL 8.0.46: focused recovery plus existing non-GUI presenter cases:
  **5 passed** (`.reports/transfer-recovery-focused.xml`). Covers legacy UNKNOWN,
  read-only lookup, exact retry rejection with unchanged DB counts, retained body,
  corrected creation, committed replay, forbidden actor and key/body mismatch.
- Real Tk/Xvfb new-form/reset and same-warehouse save validation: **1 passed**
  (`.reports/transfer-widgets.xml`). Corrected destination sends the right body.
- Existing transfer dispatch/partial receipt/completion/reconciliation and route,
  source, excess quantity, permissions/current replay cases: **2 passed** on
  disposable MySQL (`.reports/transfer-regression.xml`).
- Ruff and diff whitespace checks passed. Artifact validator passed using the
  installed release interpreter (system Python lacks openapi_spec_validator).
- The broader transfer run encountered
  `test_transfer_reparent_between_discovery_and_locks_rejects_unlocked_path` and
  was interrupted to isolate it. On the unmodified base in a separate worktree,
  that same test fails at line 208 with `moved == False` on MySQL
  (`/tmp/wms-transfer-recovery-baseline/.reports/transfer-baseline.xml`).
  The full transfer suite is not claimed green; no existing test was changed/skipped.

## Operator recovery

Restart desktop to load the form fix. In the original account's recovery journal,
select the existing UNKNOWN POST transfers and explicitly use retry with the same
key. Lookup alone remains OPERATION_UNCONFIRMED when there is no committed ACK.
The exact invalid request is rejected and retained as CONFLICT. Then start a new
transfer and choose a destination different from the source. Operators retain
control of all business actions; this patch does not send the queued request.

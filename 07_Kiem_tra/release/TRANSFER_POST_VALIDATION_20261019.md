# Transfer posting validation and recovery — 19/10/2026

Branch: `fix/transfer-receive-validation-20261019`; base `e110bfa`.

## Trigger and behavior

The first receive request on TRF-20261019-00032701 had empty `reason` and
`evidence_ref`. FastAPI rejected it before the command handler; the desktop
journal retained UNKNOWN and correctly refused a different request on the same
path. Filling the form later could not alter the frozen request.

- Desktop validates OrderAction and the typed posting/discrepancy/loss body before
  creating a journal entry. A reason/evidence error gives a concise field hint.
- Narrow pre-handler recovery for POST transfers/{id}/dispatch and /receive with
  blank reason and/or evidence. Only these two validation-error fields qualify.
  The remaining exact body shape must pass the normal contract. A local candidate
  used to validate that shape is never executed, sent or saved.
- Read-only proof requires current authenticated posting permission and assignment,
  actor/key lock, no committed HTTP key, no execution record, and matching document
  version/state. Failure to prove any condition preserves UNKNOWN.
- On successful proof, existing middleware binds X-WMS-Rejected to the original
  request digest. Existing desktop recovery retains the exact body/key as CONFLICT.
  No handler is run by lookup. The operator then sends a new fully populated request.
- No schema, migrations, role grants or business/journal data changed by deployment.

## Validation

- Disposable MySQL 8.0.46: **23 passed**, 4 GUI cases deselected
  (`.reports/transfer-post-validation.xml`). Includes 16 local blank/short/long field
  cases, real dispatch/receive recovery, unchanged balances/ledger/version during
  lookup, corrected single posting and replay, stale/unauthorized/invalid-body
  rejection protections, prior same-warehouse recovery and presenter regression.
- Real Tk/Xvfb receive button: **1 passed** (`.reports/transfer-post-widgets.xml`),
  blocks blank evidence and sends correctly validated body when filled. Initial
  test fixture omitted receive_day; fixed fixture to reflect a loaded document.
- Ruff and diff whitespace checks passed. Artifact update/check run before commit.
- Full transfer suite not rerun: prior known MySQL reparent-test failure is documented
  in TRANSFER_RECOVERY_20261019.md; no existing test was altered or skipped to hide it.

## Operator steps

Restart desktop, log in as the original actor, open recovery and select UNKNOWN
POST transfers/bb33c590-b89a-4f44-8356-77f67f6996a6/receive. Tra ACK now certifies
this invalid request as CONFLICT while the document remains PARTIAL v4. Reload
the existing transfer, fill reason and actual receiving evidence, select one unit
and BD-RECEIVING, and explicitly receive. No replacement transfer is needed.

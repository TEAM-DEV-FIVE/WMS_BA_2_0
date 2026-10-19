# Issue cancellation validation and recovery — 19/10/2026

Base: `7d95269`; branch: `fix/issue-cancel-validation-20261019`.

After cancelling the active picking task, reloading an issue clears its reason.
The desktop previously sent cancellation with an empty reason; HTTP 422 arrived
before the command handler and left its immutable journal entry UNKNOWN.

## Change

- Validate the shared OrderAction fields before issue mutations reach the presenter.
  Invalid reasons now show the 3–2000 character requirement without journaling a request.
- Add a narrow pre-validation rejection proof for ISSUE cancellation only: exact body
  shape, blank reason, integer expected version, live document visibility and
  document.cancel permission, actor/key lock, no existing command record, matching
  document version and cancellable status. This does not execute cancellation.
- A confirmed lookup turns a legacy UNKNOWN entry into CONFLICT through the existing
  recovery protocol. Its original body and key remain unchanged.
- No migrations, permission changes or operational stock/journal writes were made.

## Validation

- New suite on disposable MySQL: 27 passed (25 validation tests and 2 integration tests).
- Real Tk cancel button under Xvfb: 1 passed.
- Strengthened key/permission regression plus existing return and issue lifecycle tests:
  4 passed on disposable MySQL.
- Ruff and git diff checks passed. Artifact checks run after report generation.
- Known dependency warning: Starlette TestClient/httpx deprecation.

## Local runtime deployment

Four changed production modules were compared byte-for-byte with the base before
replacement, backed up and atomically installed. Backup:
`/home/kien/.local/share/wms-local-server/hotfix-backups/issue-cancel-validation-20261019T083850Z`.
The user API service was restarted; health and readiness both returned HTTP 200.
The desktop must restart to load the new input validation.

## User recovery

In the original Kiên account, restart the desktop, open Nháp & phục hồi lệnh and
look up the UNKNOWN `documents/.../cancel` command for ISS-20261008-00000025.
After confirmed rejection/CONFLICT, reload the issue, enter a fresh nonempty reason
and cancel. The assistant has not cancelled the operational issue or modified its
reservations. Check the resulting cancellation and released reservations before
resuming the BD-BIN-5 count freeze.

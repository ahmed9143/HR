# HR Enterprise V8.0 — Enterprise Ultimate

## Correctness / Security
- Payroll locked rows are immutable except SuperAdmin flow.
- Leave approval checks employee scope and approval permission.
- Overtime approval checks employee scope and approval permission.
- Session state is revalidated against the database.
- Sensitive exports mask National ID / IBAN without `sensitive.view`.
- Uploads use extension, size and file-signature validation.
- Public health exposes only online/version/server name.

## Attendance Engine
- Shift-aware late calculation.
- Cross-midnight work hours.
- Daily Late Limit Ledger.
- Monthly late threshold.
- Automatic warning / disciplinary events.
- Holiday table foundation.

## Enterprise HR
- Employee 360.
- Evaluation weights and trend.
- Documents/versioning/checksums.
- Enterprise Center: expiring documents, credentials, training, holidays, approvals, assets.
- Network/connected-device center.
- Backup verification and retention.
- Excel/CSV/Paste/Folder import workflows.

## Scalability
- SQLite WAL retained for LAN small/medium deployments.
- Query indexes added for major HR workloads.
- Scope filtering moved into SQL for attendance.

## Testing
`TEST_FINAL.py` is updated for V8.0 and checks package assets, public/private health, authentication, diagnostics, folder picker, exports and protected state.

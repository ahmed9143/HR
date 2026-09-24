# HR Hospital ZKTeco V16 — Final Stability Cleanup

## Final hardening completed
- Centralized background-job runtime for heavy HR operations and ZKTeco adapters.
- Added server-side job deadlines and watchdog handling.
- Added cooperative cancellation events and fast cancellation responses.
- Added bounded/best-effort job telemetry persistence so SQLite contention cannot hold an HTTP request for the full database timeout.
- Kept GET routes for employee export/folder operations navigation-only; writes/heavy processing are POST-only.
- Removed the malformed legacy Bulk QR JavaScript implementation from `v13_security_ux.py`.
- Converted old Employee Operations export/folder links to POST actions.
- ZKTeco Reconcile/Time/Sync/Provision now use the central job lifecycle when the final layer is installed.
- Optimized employee export to reuse one read-only SQLite connection instead of opening one connection per employee.
- Updated the scope/security acceptance test to use the documented bootstrap password and the new background QR response contract.
- Added `TEST_STRESS_FINAL.py` for concurrent heavy operations, normal-page responsiveness, and cancellation.

## Validation
- `TEST_V16_FINAL_STABILITY.py` — PASS
- `TEST_ENTERPRISE_STABLE.py` — PASS
- `TEST_FINAL.py` — PASS
- `TEST_ZK_HOSPITAL.py` — PASS
- `TEST_FLEX_ACCEPTANCE.py` — PASS
- `TEST_SCOPE_GET_SECURITY_UX.py` — PASS
- `TEST_STRESS_FINAL.py` — PASS in dedicated stress runs
- `python -m compileall -q .` — PASS

## Notes
A stress run can intentionally leave a large export running longer than the short stress-test observation window; the test therefore cancels the long export and verifies cancellation responsiveness rather than requiring the export itself to finish during the stress window. The normal full stability test separately verifies a complete export job.

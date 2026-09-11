# V16 Production Final Hardening

## Job engine
- Centralized heavy operations on the final job engine.
- Legacy enterprise job helpers now act as compatibility facades and delegate to the central engine after final installation.
- Added persistent `process_token` ownership to job rows.
- Fixed the job persistence UPSERT so `process_token` is actually stored.
- Added `job_processes` heartbeat registry to distinguish live worker processes from crashed ones.
- Restart recovery now marks only jobs belonging to genuinely stale processes as interrupted.
- Added a persistent SQLite unique partial index preventing duplicate active jobs for the same `(kind, owner)`.
- Added DB-backed global active-job limit (`MAX_ACTIVE_JOBS`) inside an atomic transaction.
- Added cleanup/recovery for duplicate active rows during migration.
- Added deadline checks before expensive per-item work and propagated cancellation/deadline signals to external job adapters.

## ZKTeco
- ZKTeco operations use the central job lifecycle.
- Sync/provision/reconcile/time handlers accept cancellation/deadline context.
- Existing device/network timeouts remain enforced at the adapter layer.

## Reliability
- GET handlers remain read-only for heavy operations.
- Background telemetry is best-effort and short-timeout so it cannot hold HTTP requests behind SQLite locks.
- Cancellation remains cooperative; external libraries cannot be force-killed safely from Python threads.

## Validation
- `TEST_V16_FINAL_STABILITY.py` PASS
- `TEST_STRESS_FINAL.py` PASS
- `TEST_PRODUCTION_TORTURE.py` PASS
- `TEST_ARCHITECTURE_FINAL.py` PASS
- `TEST_ENTERPRISE_STABLE.py` PASS
- `TEST_FINAL.py` PASS
- `TEST_ZK_HOSPITAL.py` PASS
- `TEST_FLEX_ACCEPTANCE.py` PASS
- `python -m compileall -q .` PASS

## Final Production Readiness Pass — 2026-09-09
- Added `PRODUCTION_PREFLIGHT.py` for offline deployment validation.
- Added `BACKUP_NOW.py` for operator-triggered verified backups.
- Added `ZK_HARDWARE_CHECK.py` for non-destructive real-terminal connectivity/attendance diagnostics.
- Added Arabic production runbook: `docs/PRODUCTION_RUNBOOK_AR.md`.
- Backup subsystem now optionally mirrors verified archives to `backup_network_path` and verifies the mirrored copy.
- Storage health now reports available free disk space.
- HTTPS mode now emits HSTS in addition to existing security headers.
- Existing central job engine, duplicate protection, cancellation, persistence/recovery, and stress/torture coverage retained.
- Real physical ZKTeco validation remains an on-site step because no physical terminal is available in the development environment.

## QR legacy-schema hotfix
- Fixed production QR generation against legacy `qr_identities(token TEXT NOT NULL)` databases.
- Startup migration backfills `token_hash` from legacy tokens where available.
- QR create/regenerate writes populate the legacy `token` column when it exists, while retaining the hashed-token verification model.
- Bulk QR generation now works against both current and legacy QR schemas.
- Added `TEST_LEGACY_QR_SCHEMA.py` covering individual and bulk QR generation on a legacy schema.

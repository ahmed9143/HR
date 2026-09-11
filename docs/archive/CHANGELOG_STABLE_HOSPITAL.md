# Stable Hospital Hardening

- Bulk Users and Bulk QR now run as background jobs and never hold the browser request open.
- Added job progress/status endpoint with per-employee success/failure reporting.
- Sidebar simplified by hiding internal/duplicate tools from the primary navigation.
- Heavy operations remain available from their feature pages for administrators.
- Existing permissions, CSRF, employee scope, audit, QR and user-creation logic are reused.
- No new external dependency required.

## Final Full Completion — 2026-09-05
- Rebuilt final navigation as a compact small-hospital sidebar.
- ZKTeco is exposed from Administration as one entry; its existing device/sync/unmatched/attendance pages remain accessible internally.
- Moved Bulk Users, Bulk QR, QR Generate All/Bulk, Full Provisioning, Full Export, and Employee Folders to the final background Job Manager.
- Added per-item failure isolation and bounded job polling; transient polling failures no longer create infinite loading.
- Kept a bounded legacy `/qr/generate-all?offset=&limit=` compatibility path for existing AJAX clients.
- Installed the final stability layer before `main()` so it is active in real startup, not only in imported/test contexts.
- Added final architecture/deployment profile: `docs/ARCHITECTURE_HOSPITAL_FINAL_AR.md`.
- Verified syntax and project acceptance/security/scope/supplies/import/ZKTeco tests.

## V16 Stability Consolidation — 2026-09-05
- Fixed the real QR ZIP Export runtime crash caused by an out-of-scope `_job_start` reference.
- QR ZIP Export now uses the persistent SQLite `bulk_jobs` engine, scoped totals, keyset pagination, `ZipFile.write()`, atomic `.part` output, and cleanup on failure.
- Final `/qr/generate-all` and `/qr/bulk` routes now use the persistent QR batch engine with one SQLite connection and commits every 50 items; the duplicate RAM-only QR job path is no longer used for these routes.
- Removed nested audit writes from the connection-owned QR bulk helper, preventing SQLite lock/deadlock behavior during bulk QR generation.
- Removed the duplicate ZKTeco attendance fetch from the hospital sync path.
- Wired ZKTeco sync cancellation into the persistent job lifecycle and made retry backoff cancellation-aware.
- ZKTeco fatal job exceptions remain `failed`; cancellation ends as `cancelled` rather than falsely reporting success.
- Added `cancel_requested` self-healing migration to `zk_jobs`.
- Runtime-tested server initialization, persistent QR bulk generation, QR ZIP creation, ZIP integrity, and full Python compilation.

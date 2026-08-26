# HR Enterprise — Final Hardening

This package preserves the existing HR application and adds/finalizes the completion layer.

## Implemented in source
- Writable Windows data root under `%PROGRAMDATA%\HR Enterprise\Data` with centralized DB/storage paths.
- Idempotent schema initialization and migrations.
- Flexible Excel upload/paste/drag-drop pipeline with preview, mapping, validation, duplicate decisions, Employee-ID review and error export.
- QR identity lifecycle: create, stable token, regenerate, revoke, verify, audit, scanner fallback.
- Printable single/bulk employee ID cards and PDF export with bundled Unicode font support.
- Contract records with history/renewal and expiry handling.
- Training records with migration from the legacy training table.
- Evaluation cycles, submissions and approval.
- Real-database HR alerts; contract/training alerts use the completion tables when present.
- Backup verification and rollback workflow.
- Windows CI build/test workflow for PyInstaller + Inno Setup.

## Important deployment rule
The executable directory is treated as read-only. Runtime data belongs under ProgramData. The app must not require the end user to run Python, PowerShell, CMD, BAT or VBS.

## CI truth
The Linux development environment can validate Python, schema, HTTP logic and source packaging. Actual Windows EXE/installer execution must be performed by the included GitHub Actions Windows runner; the workflow is configured to fail on test/build/artifact errors.

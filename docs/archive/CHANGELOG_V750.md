# V7.5.0 Hardening Changelog

## Fixed / hardened
- Fixed dashboard crash when all evaluation scores are zero (`ZeroDivisionError`).
- Fixed regression package mismatch by restoring `START_HR.bat`, `START_NETWORK_SERVER.bat`, `START_CLIENT.bat` and updating the regression test.
- Fixed Windows build typo and moved build instructions to a clean one-click EXE workflow.
- Public `/health` no longer exposes database/storage internals.
- Added authenticated `/system/health.json` with DB, storage, audit and server identity checks.
- Live session validation now checks active user, role, scope, permission version and session revocation.
- Changing user role/scope or toggling a user increments `permission_version`.
- Added deterministic first-server startup election to reduce simultaneous server startup races.
- Added server identity + fingerprint trust-on-first-use; a changed fingerprint is rejected instead of silently accepted.
- Persistent Windows data moved to `%ProgramData%\HR Enterprise\Data` when running the EXE.
- Added migration from legacy `data` beside the EXE on first V7.5 Windows start.
- Backup packages are verified by manifest/checksum before being recorded; restore validates ZIP integrity first.
- Automatic backup pruning added for daily/weekly/monthly retention buckets.
- Added optional Windows Explorer clipboard bridge using bundled pywin32 (no installation required on target PCs).
- Restored standalone HTML/CSV export endpoints and improved standalone HTML output.
- PDF reports now use bundled DejaVu Sans when available for Arabic-capable rendering.
- Employee import writes are transactional: failures roll back the whole import operation.

## Deployment
- Target PCs require only `HREnterpriseV75.exe`.
- No Python, pip, PowerShell, BAT, Internet, or manual dependency installation is required on target PCs.
- LAN multi-device mode still requires a shared local network between clients and the central server.

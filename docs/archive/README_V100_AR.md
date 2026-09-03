# HR Enterprise 10.0 — Enterprise Complete

## Included

- Excel Enterprise Grid: range selection, multi-cell paste, copy/cut, undo/redo, fill down/right, row/column add/delete, keyboard navigation, search, live validation.
- Strict employee import: validation before commit, duplicate detection, National ID checks, email/date checks, atomic commit.
- HR Intelligence: alert rules, active alert events, document/license/contract/training alerts, evaluation anomaly engine.
- Evaluation Intelligence: department/unit/job averages, relative difference %, percentile, z-score and review-only anomaly explanation.
- Matching Center: candidate selection, safe-match bulk accept, remembered decisions.
- My HR: profile, requests, payroll/payslip view, documents, training, evaluation, notifications.
- Workflow audit tables for request stages and comments.
- Connected Devices: heartbeat, latency events, trust tables and device registry.
- Branding profiles: login/sidebar/report/favicon foundations.
- Windows EXE + Inno Setup build scripts.
- PostgreSQL production schema and Docker Compose option under `postgresql/`.

## Default local administrator

Username: `admin`
Password: `<HR_BOOTSTRAP_PASSWORD>`

Change the password immediately after first login.

## Windows build

On a Windows build machine:

1. Install Python 3.11+.
2. Run `BUILD_WINDOWS_EXE.bat`.
3. Run `BUILD_INSTALLER.bat` after the EXE is created.
4. The installer output is `installer\HR Enterprise Setup.exe`.

The development machine is the only machine that needs Python/build dependencies. The installed application does not require the end user to run Python, PowerShell or CMD manually.

## Important deployment note

The packaged desktop/server mode remains SQLite-first because it is zero-configuration. PostgreSQL assets are included for central production deployment; the current monolithic SQLite adapter is not silently switched to PostgreSQL by the installer.

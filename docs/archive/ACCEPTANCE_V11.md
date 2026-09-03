# HR Enterprise V11 — Acceptance Checklist

The goal is feature completeness without overengineering.

- Excel: drag range, Shift/arrows, copy/cut/paste, undo/redo, fill down/right, add/delete rows/columns, resize, Tab/Enter.
- Import: preview, duplicates, required fields, email/date validation, atomic commit.
- Mapping: saved reusable mappings with confidence/version.
- Matching: candidates, confidence, accept/reject/ignore, remembered decisions, safe bulk.
- My HR: profile, requests, payroll/payslip, documents, training, evaluation, notifications.
- Workflow: submit → manager → HR → approve/reject, comments, reopen/cancel, audit.
- Intelligence: alerts + read/snooze action lifecycle.
- Devices: heartbeat, online/offline, approve/revoke/rename/disconnect.
- Existing V10 reports/export/PDF/print, payroll and RBAC are retained.
- Saved Views and Global Search are included.
- Windows build/installer scripts and tray/autostart sources are included.
- PostgreSQL migration and health utilities are included.

A real Windows binary and a real PostgreSQL server run are environment-dependent; the package does not falsely label those as already executed here.


## V11.1.1 Hardening Gate

Before release, run `python v11_feature_patch.py .` and require every source feature marker to be PASS and every Python file to compile. Run `TEST_V11_ACCEPTANCE.py` as the release smoke test.

### Environment-dependent gates
- Windows EXE/installer: must be built and launched on a real Windows machine.
- PostgreSQL: must be started and the application must run against `HR_DB_URL`; migration must be followed by row-count/schema verification.
- Multi-user: run the included concurrency test against the real target database, not SQLite-only.

These are release gates, not claims that this Linux build environment has executed them.

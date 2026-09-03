# HR Enterprise V9.0 Complete

هذه النسخة مبنية على V8.3 وتجمع طبقات HR Intelligence + Employee Self-Service + Excel Center Pro + Multi-user/network foundation.

## أهم الوحدات
- HR Intelligence & Alerts Center
- Employee Risk / Attention indicators
- Employee Self-Service: Profile, Attendance, Leaves, Overtime, Payroll, Documents, Training, Evaluation, Notifications
- Employee Requests workflow: Employee -> Manager -> HR
- Excel Center Pro: multi-cell paste, edit cells, add/delete rows, search, fill-down, undo/redo, validation highlighting
- Validate -> Preview -> Confirm atomic paste import
- Matching Center + safe matches review
- Evaluation Intelligence: department average, delta %, percentile, anomaly review indicator
- Connected Devices + heartbeat + latency
- Server Discovery UX
- Branding Manager: Login / Sidebar / Report / Favicon profiles
- Payroll Ready for Lock alert
- Existing backups, audit chain, permissions, imports, documents, payroll, attendance, shifts, notifications and diagnostics

## Windows
- `BUILD_WINDOWS_EXE.bat` builds `HR Enterprise.exe` on a Windows build PC.
- `BUILD_TRAY_EXE.bat` builds the optional tray component.
- `INSTALL_OPTIONAL_AUTOSTART.bat` enables Windows user auto-start.

## Security
- CSRF on state-changing POSTs
- Role/permission checks
- Employee self-scope resolution does not trust a client-supplied employee code
- Atomic validation before paste import commit
- Audit/error logging

# HR Enterprise V11 — Feature Complete Package

الهدف: إغلاق الـ Features وتصحيح الـ UX والـ business logic بدون إعادة بناء معقدة.

## أهم ما تم إغلاقه في طبقة V11
- Excel Grid: mouse drag ranges، Shift/Arrow selection، clipboard، undo/redo، fill down/right، add/delete rows/columns، resize.
- Smart Mapping: حفظ mapping لكل مستخدم/شركة مع confidence/version.
- Workflow: transitions + comments + audit + reopen/cancel.
- Notifications/Intelligence: read/snooze action history.
- Devices: approve/revoke/rename/disconnect + online/offline display.
- Saved Views + Global Search.
- PostgreSQL migration + health utilities.
- Acceptance checklist + tests.

## التشغيل
- للاختبار المحلي: استخدم ملفات التشغيل الموجودة في المشروع.
- Windows EXE/Installer: شغّل BUILD_WINDOWS_EXE.bat ثم BUILD_INSTALLER.bat على جهاز Windows.
- PostgreSQL: شغّل PostgreSQL ثم استخدم `postgresql/migrate_sqlite_to_postgres.py` و`postgresql/verify.py`.

## مهم
هذه النسخة لا تضيف microservices أو framework جديد. V10 يبقى الأساس، وV11 يضيف طبقة Features مباشرة فوقه.

## V12 Enterprise Final additions
- QR Identity: stable opaque tokens, verification, regenerate/revoke, audit, USB/manual scanner and camera fallback.
- Printable Employee ID Cards: single, bulk and PDF, with QR and optional employee photo.
- Contract lifecycle records with renewal/history.
- Training records and certificate expiry tracking.
- Evaluation cycles, submission, approval and history.
- Windows GitHub Actions build/installer pipeline.

# HR Enterprise Finalization QA

Version: 12.0.0-Enterprise-Final

## PASS in Linux sandbox
- Python compilation for all project Python files.
- Existing TEST_FINAL regression suite, updated for current version, PASS.
- TEST_V10_COMPLETE PASS.
- TEST_V90_COMPLETE PASS.
- TEST_V11_ACCEPTANCE PASS (0 failures).
- TEST_MULTI_FOLDER_IMPORT PASS.
- Live server startup and /health.
- Login/session flow used for live feature testing.
- QR PNG generation; decoded payload is `/qr/verify/<opaque-token>`.
- QR/profile, scanner, single ID card, bulk ID card, and PDF ID card routes load successfully.
- Contracts page and database write tested.
- Training page and database write tested.
- Evaluation cycle, evaluation submission, and database write tested.
- SQLite schema additions initialize automatically.

## NOT TESTABLE in this Linux sandbox
- Real Windows EXE execution and installer GUI.
- Physical USB QR scanner hardware.
- Physical camera hardware.
- Live PostgreSQL server/multi-machine deployment.

## Windows automation added
- `.github/workflows/windows-build.yml`
- PyInstaller build with qrcode/reportlab collection.
- Inno Setup installer build.
- Artifact verification; critical CI steps fail the job.

## Important
The application still uses its existing single-file `http.server` architecture plus V10/V11 layers. This release adds a dedicated completion layer rather than rewriting the existing application.

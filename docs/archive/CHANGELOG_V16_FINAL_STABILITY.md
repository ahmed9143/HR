# V16 Final Stability Hardening

## Background Jobs
- Unified the legacy enterprise bulk-job API and employee operations around one background-job engine.
- Added persistent job progress through `bulk_jobs` for the common job API.
- Added per-job server-side watchdog timeouts.
- Added cooperative cancellation events and cancellation endpoints.
- Workers stop between items when cancellation/timeout is requested.
- Job history is cleaned up after a bounded retention period.

## QR / ID Cards
- Individual QR generation/regeneration remains asynchronous.
- Bulk QR no longer uses the legacy synchronous request path.
- Legacy QR bulk pages now follow the background-job redirect correctly.
- Opening/printing an ID card no longer creates a QR as a side effect of GET.

## ZKTeco
- ZKTeco jobs now use the same central job engine where the final layer is loaded.
- Reconcile and device-time operations remain background jobs.
- Cancellation/timeout events are shared with the central job manager.
- Polling has request-level timeouts and bounded monitoring.

## GET Safety
- Legacy `/employee/operations/export` and `/employee/operations/folders` GET endpoints are navigation-only.
- Heavy/write operations are launched from explicit POST actions.

## SQLite / Concurrency
- SQLite connection busy timeout is bounded at 10 seconds.
- WAL remains enabled.
- Background progress persistence is throttled so it does not create a commit per item.

## Acceptance / Regression Tests
- Fixed acceptance tests to use the real offline bootstrap password instead of an obsolete environment-variable password.
- Added `TEST_V16_FINAL_STABILITY.py` covering:
  - background QR launch
  - concurrent navigation while QR runs
  - unified legacy job status
  - server-side completion
  - GET ID-card read-only behavior
  - background export
  - cancellation endpoint
  - static timeout/SQLite guards
- Verified passing suites:
  - `TEST_ENTERPRISE_STABLE.py`
  - `TEST_V16_FINAL_STABILITY.py`
  - `TEST_FINAL.py`
  - `TEST_V14_FINAL_SECURITY.py`
  - `TEST_ZK_HOSPITAL.py`
  - `TEST_FLEX_ACCEPTANCE.py`
  - `python -m compileall -q .`

# QR Loading / SQLite Contention Fix

## Problem fixed
Bulk QR generation was already running in a background thread, but each QR still performed its own SQLite write transaction and audit() call. Under a real hospital roster this could create a continuous stream of SQLite write locks, making unrelated browser requests appear to keep loading.

## Production fix
- Bulk QR now renders QR PNGs without holding a SQLite write transaction.
- QR database updates are committed in short batches of 25 employees.
- Audit-chain entries are appended in the same short transaction as the QR updates.
- QR image files are written to temporary files and atomically moved into place after the database commit.
- Duplicate active QR generation remains protected.
- Cancellation and server-side timeout remain supported.
- Individual QR generation remains a background job and does not block the HTTP request.

## Validation
The following tests pass after the fix:
- TEST_V16_FINAL_STABILITY.py
- TEST_STRESS_FINAL.py
- TEST_PRODUCTION_TORTURE.py
- TEST_ARCHITECTURE_FINAL.py
- TEST_ENTERPRISE_STABLE.py
- TEST_FINAL.py
- TEST_ZK_HOSPITAL.py
- TEST_FLEX_ACCEPTANCE.py
- TEST_PRODUCTION_PREFLIGHT.py
- python -m compileall -q .

## Remaining real-world validation
The final step is to run the application in the real hospital environment with the actual employee database and, separately, validate the ZKTeco hardware. No software test can substitute for that hardware/network validation.

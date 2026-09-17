# Automated Test Report — v17 final regression

Executed from a clean environment (no database, no keys, no bytecode cache),
each suite run directly rather than through a wrapper.

Host: Linux container, Python 3.12. **No result here was produced on Windows.**

**34/34 passed**

| Suite | Tests | Result |
|---|---|---|
| `tests/unit/` (5 files) | architecture, v10, v11, v12, v90 | PASS |
| `tests/integration/` (10 files) | enterprise, final, flex, ID designer, legacy QR schema, folder import, preflight, QR workflow, supplies, ZK hospital | PASS |
| `tests/security/` (12 files) | concurrency, diagnosability, leave authz, scope fix, **QR authorization**, **QR token secrecy**, route collisions, scope GET, scope POST, v14 security, v17 hardening, ZK credentials | PASS |
| `tests/stress/` (3 files) | torture, stress, v16 stability | PASS |
| `tests/dr/` (1 file) | disaster recovery 22/22 | PASS |
| `tests/e2e/` (2 files) | browser E2E 23/23, CSP 10/10 (real Chromium) | PASS |
| `tests/load/` | 500 / 1,000 / 5,000 employees + 100k attendance | MEASURED |

## Negative controls

Each of these was confirmed to FAIL with the fix disabled and PASS with it
enabled. A test that cannot fail proves nothing.

| Fix | Without fix | With fix |
|---|---|---|
| `/id-cards` bulk QR button | FAIL — `onclick="genAllQr()"` unresolved, 0 controls | PASS 17/17 |
| Browser E2E dangling-handler probe | FAIL — `genAllQr()` reported | PASS 23/23 |
| Permission-cache generation guard | FAIL — revoked permission cached permanently | PASS 8/8 |
| QR images in backups | FAIL — `0/8` images restored | PASS — `8/8` |

## Not executed here

| Area | Reason |
|---|---|
| Windows runner (ACL, PyInstaller, service) | No Windows host available |
| Real ZKTeco device | No physical terminal available |
| PostgreSQL end-to-end | No PostgreSQL server available |

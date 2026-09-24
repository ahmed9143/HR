# Test Matrix — HR Enterprise v17

Status vocabulary is strict: **PASS** means the test was executed in this
session and passed. **BLOCKED** means it could not be executed. Nothing is
marked PASS on the strength of source-code inspection alone.

| CATEGORY | TEST | RESULT | EVIDENCE | BLOCKER |
|---|---|---|---|---|
| Startup | Server boots, `/health/ready` 200 | PASS | `TEST_QR_IDCARDS_WORKFLOW.py`, `TEST_BROWSER_E2E.py` | — |
| Startup | Clean first run generates random admin password | PASS | `TEST_V17_HARDENING.py` | — |
| Login | Valid login (browser) | PASS | Browser E2E | — |
| Login | Invalid login rejected (browser) | PASS | Browser E2E | — |
| Login | Forced password rotation (browser) | PASS | Browser E2E | — |
| Login | Logout invalidates session (browser) | PASS | Browser E2E | — |
| Login | Persistent per-IP + per-user lockout | PASS | `TEST_V17_HARDENING.py` | — |
| Login | No username enumeration | PASS | `TEST_V17_HARDENING.py` | — |
| RBAC | Unauthenticated `/id-cards` blocked | PASS | `TEST_QR_IDCARDS_WORKFLOW.py` | — |
| RBAC | Unauthenticated `POST /qr/generate-all` blocked | PASS | `TEST_QR_IDCARDS_WORKFLOW.py` | — |
| RBAC | Scope enforcement (existing suite) | PASS | `TEST_SCOPE_GET_SECURITY_UX.py`, `TEST_SCOPE_POST_ENDPOINTS.py` | — |
| RBAC | Bulk QR has exactly one enforcement point | PASS | `TEST_QR_AUTHORIZATION.py` 16/16 | — |
| RBAC | Contradictory `is_admin` guard deleted from v13 | PASS | Same | — |
| RBAC | unauthenticated / Employee / Manager denied by the server | PASS | Same — direct HTTP, not hidden buttons | — |
| RBAC | Admin + HR allowed (prior behaviour preserved) | PASS | Same | — |
| RBAC | Revoke via Roles screen blocks on the next request | PASS | Same | — |
| RBAC | **Out-of-band revoke never reached the cache** (no TTL) | FIXED | Same — TTL added, proven both directions | — |
| QR | **Third writer still stored plaintext tokens** (`production_ops`) | FIXED | `TEST_QR_TOKEN_SECRECY.py` 15/15 on a real legacy schema | — |
| QR | **Migrated legacy row was active with no image** | FIXED | Same — now `needs_regeneration` and rebuilt | — |
| QR | Single / bulk / regenerate paths all token-safe | PASS | Same | — |
| QR | No token or hash in HTML, JSON or logs | PASS | Same | — |
| Employees | Employee list renders rows (browser) | PASS | Browser E2E, 7 rows | — |
| Employees | Create/edit/search/photo/files lifecycle | BLOCKED | Not exercised this session | Scope — not yet written |
| QR | `/id-cards` loads without ReferenceError | PASS | Browser E2E | — |
| QR | Every inline handler resolves to a real function | PASS | Browser E2E in-page probe | — |
| QR | Bulk QR button present and clickable | PASS | Browser E2E | — |
| QR | Click → job created → redirect | PASS | Browser E2E, job `gf8PWYCbTrcbmg` | — |
| QR | Job progress UI reaches completion | PASS | Browser E2E, "اكتملت العملية بنجاح — 6/6" | — |
| QR | QR rows written to database | PASS | 6 active `qr_identities` rows | — |
| QR | QR PNG files exist on disk | PASS | 6/6 files, 14327-byte valid PNG | — |
| QR | Employee with missing data does not abort job | PASS | `TEST_QR_IDCARDS_WORKFLOW.py` (E999) | — |
| QR | Repeat/double submission handled | PASS | Button disappears when nothing missing | — |
| QR | Forged CSRF rejected | PASS | `TEST_QR_IDCARDS_WORKFLOW.py` | — |
| QR | No plaintext bearer token stored | PASS | `TEST_QR_IDCARDS_WORKFLOW.py` | — |
| QR | Single-employee QR generation | BLOCKED | Not exercised this session | Scope |
| ID Cards | ID card previews render | PASS | Browser E2E, 6 iframes | — |
| Attendance | Any attendance flow | BLOCKED | Not exercised | Scope |
| ZKTeco | Real device connect/sync/reconnect/timeout | BLOCKED | No physical device | **REAL DEVICE NOT AVAILABLE** |
| ZKTeco | Mock-level flows | PASS | `TEST_ZK_HOSPITAL.py` | Mock only — not device proof |
| ZKTeco | `comm_password` encrypted at rest (AES-256-GCM) | PASS | `tests/security/TEST_ZK_CREDENTIALS.py` 17/17 | — |
| ZKTeco | Password never rendered in UI (masked input) | PASS | Same | — |
| ZKTeco | Blank field on edit keeps stored password | PASS | Same | — |
| ZKTeco | Connector still receives the decrypted value | PASS | Same (mock adapter) | Real device still BLOCKED |
| ZKTeco | Legacy plaintext migrated on startup | PASS | Same | — |
| ZKTeco | **`MockZKAdapter` crashed on the default path** | FIXED | `self.timeout` never assigned | — |
| Jobs | Creation, progress, completion | PASS | Browser E2E + workflow test | — |
| Jobs | Cooperative cancellation | PASS | `TEST_V17_HARDENING.py` | Checkpoints verified; not load-tested |
| Jobs | Restart/stale-job recovery | BLOCKED | Not exercised | Scope |
| Database | SQLite schema init, integrity | PASS | `/health/ready`, `quick_check` | — |
| Database | PostgreSQL end-to-end | BLOCKED | Never executed | No PostgreSQL instance; `BEGIN IMMEDIATE` is SQLite-specific |
| Backup | AES-256-GCM encrypt/decrypt + tamper detection | PASS | `TEST_V17_HARDENING.py` | — |
| Restore | Full create → destroy → restore → data check | PASS | `tests/dr/TEST_DISASTER_RECOVERY.py` 22/22 | — |
| Restore | **QR images were missing from every backup** | FIXED | DR test caught `0/8`; now `8/8` | — |
| Restore | Wrong key cannot decrypt | PASS | DR test | — |
| Restore | Corrupted backup rejected | PASS | DR test | — |
| Restore | Recovered system boots and serves restored data | PASS | DR test | — |
| TLS | Certificate/key loading, refusal to serve plaintext on LAN | BLOCKED | Not executed this session | Package changed since last verification |
| CSP | `script-src` no longer allows arbitrary inline script | PASS | `tests/e2e/TEST_CSP.py` 10/10, real Chromium | — |
| CSP | Per-response nonce, unique per response | PASS | Same | — |
| CSP | Injected `<script>` blocked by the browser | PASS | Same — CSP violation observed | — |
| CSP | Injected `on*` handler with unknown body blocked | PASS | Same | — |
| CSP | The page's own inline handlers still execute | PASS | Same, plus E2E 23/23 | — |
| CSP | `style-src` still `unsafe-inline` | KNOWN GAP | Inline `style=` attributes are pervasive | Lower risk; next step |
| CSP | Processing cost | MEASURED | `employee_list` p50 68 → 78 ms (+15%) | Acceptable; re-measure on Windows |
| Performance | **Dashboard first request after a data change = 4.16 s** | FINDING | Per-request probe: 4160, 31, 16, 15, 15 ms … | Cold path, not root-caused |
| File Upload | Traversal/symlink/zip-bomb rejection | PASS | `TEST_V17_HARDENING.py` (`safe_extract_zip`) | Multipart fuzzing not done |
| Security | Default password unusable | PASS | `TEST_V17_HARDENING.py` | — |
| Security | Route-collision / shadowed-auth audit | PASS (tool runs) | `TEST_ROUTE_COLLISIONS.py` — **13 shadowed checks found** | Findings not yet remediated |
| Security | **Bulk QR wrote plaintext bearer tokens on legacy schema** | FIXED | `stable_final` had its own writer bypassing the earlier fix | — |
| Security | Failed QR image move no longer reports success | PASS | `TEST_DIAGNOSABILITY.py` — no active row without its file | — |
| Security | Structured JSON log with rotation | PASS | `TEST_DIAGNOSABILITY.py` 10/10 | — |
| Security | Secrets redacted from logs | PASS | Same | — |
| Security | `MockZKAdapter` default path crashed | FIXED | `self.timeout` unassigned | — |
| Performance | 500 / 1,000 / 5,000 employees | PASS (measured) | `tests/load/TEST_LOAD_BENCHMARK.py`, `docs/LOAD_RESULTS.json` | Linux host — **Windows figures still unmeasured** |
| Performance | 100,000 attendance records | PASS (measured) | Same, db 17.5 MB | Same |
| Performance | **dashboard p99 = 4.1s at 5,000 employees** (p50 = 23ms) | FINDING | Load benchmark | Cold-path outlier, not yet root-caused |
| Concurrency | Permission-cache revoke race | FIXED | `TEST_CONCURRENCY.py` 8/8, negative control confirms | — |
| Concurrency | Scope cache bounded + evicting | PASS | Same | — |
| Concurrency | Concurrent SESS mutation | PASS | Same | — |
| Database | PostgreSQL marked experimental, dependency optional | PASS | `requirements-postgres.txt`, `docs/POSTGRES_STATUS.md` | E2E still never run |
| CI | Release audit + route report + browser E2E gates added | PASS (config) | `windows-build.yml` | Not executed on a Windows runner |
| Cleanup | Dead `genAllQr` removed from shadowed handler too | PASS | Scan reports 0 live references | — |
| Browser | Chromium E2E, 23 assertions | PASS | `TEST_BROWSER_E2E.py` 23/23 | Linux Chromium, not Windows |
| CI | `windows-build.yml` correctness | BLOCKED | Not reviewed this session | Scope |
| Packaging | PyInstaller Windows build | BLOCKED | Cannot build Windows EXE on Linux | **Windows build host unavailable** |

## Negative controls

A test that cannot fail proves nothing. Both new suites were executed against
the **unfixed** `v13_security_ux.py` to confirm they detect the original defect:

| Test | On broken code | On fixed code |
|---|---|---|
| `TEST_QR_IDCARDS_WORKFLOW.py` | FAIL — "no form posting to /qr/generate-all", "undefined: ['genAllQr']" | PASS 17/17 |
| `TEST_BROWSER_E2E.py` | FAIL — `onclick="genAllQr()"` unresolved, 0 controls | PASS 23/23 |

The first version of the browser test reported "no ReferenceError" as PASS on
broken code, because the error only fires on click. That gap was closed by
adding an in-page probe that resolves every inline handler against `window`.

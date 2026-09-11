# Known Limitations — v17.0.0

This document exists so nobody has to rediscover these by being surprised in
production. Everything here is a **deliberate** remaining gap, not an oversight.

---

## 1. The monkey-patching architecture is unchanged

`server.py` sequentially imports thirteen modules, each calling
`install(globals())` to wrap `H.do_GET` / `H.do_POST` and replace functions
defined by the layer before it:

```
server → v10 → v11 → enterprise_completion → v12 → production_ops
       → zkteco_core → zkteco_sync → zkteco_ui → zkteco_hospital
       → v13 → v14 → stable_final
```

Route precedence, permission checks and feature behaviour all depend on this
import order. Reordering two lines can silently change which handler wins.

**Why it was not fixed:** replacing it with a modular router touches every
route in the product. Doing that *before* the security and reliability work
would have meant shipping a large untested refactor on top of a system with a
known default admin password. The correct order is security → reliability →
architecture, and this pass covers the first two.

**Mitigating fact:** the imports have no `try/except`, so a failed import
crashes loudly at startup rather than silently disabling a security layer.

---

## 2. CSP still requires `unsafe-inline`

Current policy:

```
script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'
```

**Why it was not fixed:** a nonce-based CSP does not cover inline event
handlers, and the templates use `onclick="..."` extensively across five files.
Adding a nonce would not tighten anything until every inline handler is moved
to an addEventListener in a static file — a frontend refactor, not a header
change. Claiming a strict CSP while `unsafe-inline` remains would be worse than
the honest current state.

**Compensating control:** the one known server-data-into-`innerHTML` sink (job
error rendering) has been converted to `textContent`. Any new `innerHTML` usage
that receives server data should be treated as a defect.

---

## 3. Testing that was NOT performed

The automated suite passes (see `docs/TEST_REPORT.md`), but the following
require resources unavailable in this environment. **Do not describe the system
as production-ready until these are done.**

| Gap | What is needed | Why it matters |
|---|---|---|
| Browser E2E | Playwright/Selenium against a real browser | The original "stuck loading" symptom appeared *in the browser*. Server-side tests cannot reproduce navigation during Bulk QR, multiple tabs, refresh mid-job, or cancel-then-download. |
| Real ZKTeco hardware | A physical device | Mock tests do not cover connect/disconnect, large attendance pulls, bad network, time sync, reconnect, or cancellation against real firmware. |
| PostgreSQL end-to-end | A live PostgreSQL instance | `pg_compat.py` is not verified against the job engine's `BEGIN IMMEDIATE`, which is SQLite-specific. See §4. |
| Realistic load | 500 / 1,000 / 5,000 employees, 100k attendance rows, 10k documents | SQLite writer contention under concurrent HR users + ZKTeco sync + export + backup is the remaining plausible source of slowness. `/health/deep` now measures it, but the measurement has not been taken under real load. |
| Disaster recovery drill | A clone to destroy and restore | A backup that has never been restored is a hypothesis, not a backup. Measure RPO/RTO. |
| Fuzzing | multipart / ZIP / CSV / QR token / query params | `parse_upload()` is a hand-written multipart parser handling sensitive HR files. |

---

## 4. PostgreSQL is not a supported production mode

`pg_compat.py`, the PostgreSQL schema and `docker-compose.postgres.yml` exist,
but the tests only assert that those files are present — no test runs the
application end-to-end against PostgreSQL. The job engine also uses
`BEGIN IMMEDIATE`, which is SQLite-specific.

**Decide one of two things:**

- Build a real PostgreSQL CI job (init → login → employees → QR → jobs →
  export → ZKTeco → backup/restore), **or**
- Remove PostgreSQL from the product claim in `README.md`.

Until one of those happens, treat SQLite as the only supported store.

---

## 5. Remaining `except Exception` blocks

The application code (excluding tests) still contains roughly **193**
`except Exception` handlers and **65** that end in a bare `pass`. Silent
swallowing in the DB, backup, QR, ZKTeco, session and job-engine paths is
exactly what makes a hang undiagnosable.

This pass converted the handlers it touched and added structured error logging
around the new code, but a full audit was not attempted — mechanically
narrowing 193 handlers without understanding each call site risks turning
tolerated failures into crashes. Treat it as a scheduled follow-up, working
outward from the DB and job-engine paths first.

---

## 6. ZKTeco communication passwords are still plaintext

`zk_devices.comm_password` is stored unencrypted and displayed in full in the
UI. It should move to Windows DPAPI / Credential Manager and be masked in the
interface. Not addressed in this pass.

---

## 7. Logging is still `print()`-based

`log_error()` writes `[ERROR] ...` to stdout plus a database row. Structured
JSON logging (timestamp, level, request_id, job_id, username, IP, operation,
exception) with rotation is not implemented. `/health/deep` covers the
immediate diagnostic need; proper logging remains outstanding.

---

## 8. Backups are encrypted but not immutable

Local and network backups are AES-256-GCM encrypted, but a compromised admin
account or ransomware can still delete all copies. Add an offline or immutable
tier (NAS snapshot, Windows Server Backup, rotating offline USB). Network-copy
retention is also not pruned on the same cycle as local retention.

**Critical operational note:** `data/backup.key` is the only way to read an
encrypted backup. Copy it somewhere offline. Losing it makes every backup
permanently unreadable.

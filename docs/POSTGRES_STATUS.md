# PostgreSQL Status — EXPERIMENTAL, not production-supported

## Decision

Path (A) from the hardening scope was taken: PostgreSQL is marked
**experimental**, and `psycopg[binary]` was moved out of `requirements.txt`
into `requirements-postgres.txt`.

Path (B) — implementing and validating PostgreSQL end-to-end — was **not**
attempted, because no PostgreSQL instance was available in this environment
and claiming support without an E2E run would be exactly the kind of unproven
assertion this work exists to eliminate.

## What exists

- `pg_compat.py` — a compatibility shim. It already imports `psycopg` inside a
  `try/except` and sets `psycopg = None` on failure, so the application runs
  normally on SQLite when the driver is absent.
- PostgreSQL schema files and a `docker-compose` definition.

## Why it is not supported

1. **No end-to-end validation has ever run.** The existing tests assert that
   these files *exist*, not that the application works against PostgreSQL.
2. **The job engine uses SQLite-specific transaction semantics.**
   `stable_final.py` issues `BEGIN IMMEDIATE` to claim a job slot. That is
   SQLite syntax. PostgreSQL has no `IMMEDIATE` transaction mode; the
   equivalent intent is `BEGIN` plus `SELECT ... FOR UPDATE` or an advisory
   lock. Until that is translated and tested, concurrent job claiming is
   undefined on PostgreSQL.
3. Other SQLite-specific behaviour is likely present and unaudited:
   `PRAGMA journal_mode=WAL`, `PRAGMA busy_timeout`, `PRAGMA integrity_check`,
   `INSERT OR IGNORE`, `sqlite3.Connection.backup()` (used by `make_backup`),
   and the `datetime('now')` scalar.

## What would be required to support it

A CI job running against a real PostgreSQL instance covering, in order:
init → login → employees → QR generation → background jobs → export →
ZKTeco sync → backup → restore. Plus a translation of every construct in
point 3 above, with `BEGIN IMMEDIATE` handled explicitly.

Until that job exists and passes, **treat SQLite as the only supported store**
and do not present PostgreSQL as an option to customers.

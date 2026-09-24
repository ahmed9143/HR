## [18.0.0] — Production hardening continuation

- Added configurable HR permission policy settings.
- Added permission request workflow for regular, morning, evening and emergency permissions.
- Added universal XLSX template/import/export and Excel clipboard paste for employees, leaves, attendance and permission requests.
- Added deterministic admin password recovery; no random passwords are generated.
- Added a self-contained end-user bundle check to Windows CI so Python/pip/Node are not required on hospital PCs.
- Added V18 production smoke coverage.
- PostgreSQL, real-device ZKTeco validation, browser E2E, code signing and full production DR remain explicit CI/deployment gates; they are not silently marked complete.

# Changelog

## [17.0.0-r10] — Windows application build + first-run login

### Fixed
- **"Wrong password on every new device".** The windowed EXE has no console, so
  the per-machine random first-run password was printed nowhere and written to
  the hidden ProgramData folder. First run now uses a fixed, documented default
  (`admin` / `Admin@12345`) with a forced change on first login; it applies
  only to an empty users table and never resets an existing install.
- **Security: pages reachable before the forced password change.** `/id-cards`
  (owned by `v13_security_ux`) never checked `must_change_password`. Enforcement
  now happens once, centrally, for every GET route.
- `icacls` granted `Administrators`, which does not exist by that name on
  non-English Windows; now uses the well-known SID `*S-1-5-32-544`.
- `icacls` from the windowed app flashed a console window (`CREATE_NO_WINDOW`).
- The auto-generated TLS private key used `chmod(0o600)` (a no-op on NTFS);
  now protected with a real ACL.
- `.gitignore` ignored `*.spec`, so the build definition would never have been
  committed and CI would have failed on its first run.
- The installer referenced a network-server EXE that no script built, and
  carried a stale version 11.2.6.

### Added
- `HR_Enterprise.spec` (onedir), `BUILD_WINDOWS.bat`, rewritten `HR_Enterprise.iss`.
- GitHub Actions: audit → Linux + **Windows** tests (incl. NTFS ACL check) →
  build → packaged-app smoke test → installer → release on tag.
- `tests/packaging/TEST_FROZEN_APP.py` — drives the *built* executable.
- `tests/security/TEST_FIRST_RUN.py` — a brand-new machine with no configuration.
- `.gitattributes` keeping `.bat` / `.iss` in CRLF.

### Removed
- Six drifted `BUILD_*.bat` scripts (archived under `docs/archive/legacy_build/`).

---


All notable changes to HR Enterprise. This is the **only** changelog; the
previous overlapping `*_FINAL_*` files now live in `docs/archive/`.

---

## [17.0.0] — 2026-09-10 — Production Hardening

The version jump to 17.0.0 resolves the previous split between
`README (v11.2.3)`, `VERSION.txt (11.2.7 V16)` and `APP_VERSION (11.2.6)`.
`VERSION.txt`, `APP_VERSION` and the UI now all report the same number.

### Fixed after the initial v17.0.0 tag (same release, CI-caught)

- **`HR_NETWORK_SERVER.py` ignored an operator/CI-supplied `HR_HOST`.** It set
  `os.environ['HR_HOST']='0.0.0.0'` unconditionally instead of only as a
  default, silently discarding any override. Changed to `setdefault()`. The
  real-world default is unchanged (still `0.0.0.0` when nothing overrides
  it); this only restores the ability to override it.
- See the corrected "Real TLS" entry below — the original draft of this
  changelog described a plaintext-refusal-only policy that did not account
  for existing installations having no certificate configured.

### Security — BREAKING

- **Removed the hardcoded `Admin@12345` bootstrap credential.**
  `_bootstrap_admin_password()` had regressed to returning a fixed string, so
  every new installation shared a publicly documented SuperAdmin password.
  It now resolves `HR_BOOTSTRAP_PASSWORD`, then an existing first-run file,
  then generates `secrets.token_urlsafe(18)` written to
  `data/INITIAL_ADMIN_PASSWORD.txt` (mode 0600) and printed once. The file is
  deleted automatically when the password is rotated.
  *Migration:* existing installations are unaffected — the bootstrap path only
  runs when the `users` table is empty.

- **Brute-force protection is now persistent and account-aware.**
  The old `LOGIN_ATTEMPTS = {}` dict was per-IP, in-memory (lost on restart),
  and reset its own counter after each lockout — giving an attacker unlimited
  5-attempt rounds forever. Replaced with an `auth_failures` table tracking
  **per-IP and per-username** counters, with progressive backoff
  (5m → 10m → 20m … capped at 24h) that survives a restart.
  Every outcome is written to `security_login_events`.

- **Closed username enumeration.** `checkpw()` (scrypt) previously ran only
  when the username existed, so response latency revealed valid accounts. A
  dummy hash is now verified for unknown usernames, and both cases return an
  identical message.

- **Real TLS, with a zero-config default.** `HR_TLS_CERT` / `HR_TLS_KEY` make
  the server speak HTTPS with an operator-supplied certificate. Previously
  `https_enabled=1` only added an HSTS header and a Secure cookie while the
  socket stayed plaintext.
  When the server is LAN-exposed (non-loopback) and no certificate is
  configured, it no longer refuses to start: it auto-generates a self-signed
  certificate on first run (`data/auto_tls_cert.pem`, key file mode `0600`)
  and serves real HTTPS with it. Browsers show a one-time "not trusted"
  warning per device for this internal certificate — expected, and still a
  strict improvement over plaintext. `HR_NO_AUTO_TLS=1` restores the stricter
  original behaviour (refuse to start unless `HR_ALLOW_PLAINTEXT_LAN=1` is
  set), for operators who want to enforce a real certificate.
  *Correction from the first v17.0.0 draft of this changelog:* that draft
  described a hard refusal with no auto-TLS fallback. That would have made
  every existing Network Server EXE installation refuse to start after
  upgrading, since the EXE binds `0.0.0.0` by default and none of them have a
  certificate configured today. It was caught by a CI smoke test
  (`Smoke test packaged network EXE`) failing after the `HR_HOST` override bug
  above was fixed and the refusal actually triggered for the first time.

- **Encrypted backups.** `HR_Backup_*.zip` contained `database.db` (national
  IDs, IBANs, salaries) plus every employee document in cleartext. Backups are
  now AES-256-GCM encrypted in streaming chunks with a key held outside the
  archive (`HR_BACKUP_KEY` or `data/backup.key`, mode 0600). Tampering is
  detected on restore.

- **Hardened archive restore.** `z.extractall()` is replaced by
  `safe_extract_zip()`, which rejects absolute paths, `..` traversal, symlinks,
  excessive entry counts, excessive uncompressed size and zip-bomb compression
  ratios — validating every member *before* writing anything. The restored
  database must also pass `PRAGMA integrity_check` before it replaces the live
  one.

- **Eliminated plaintext QR bearer tokens.** For backward compatibility with
  legacy `qr_identities(token TEXT NOT NULL)` schemas the code stored the real
  bearer token alongside its hash. Verification has always used `token_hash`,
  so the column now receives a `redacted-<hash-prefix>` marker, and a startup
  migration redacts any token already stored. Existing QR codes keep working.

- **HTTP request limits.** Bodies were read in full based on a client-supplied
  `Content-Length` with no ceiling. Per-endpoint limits (2 MB / 64 MB / 256 MB)
  are now enforced *before* reading, returning `413`.

- **Bounded concurrency.** `ThreadingHTTPServer` spawned unlimited threads.
  A semaphore caps concurrent requests (`HR_MAX_WORKERS`, default 48) and
  returns `503` when saturated. Socket timeouts prevent slow clients from
  holding threads indefinitely.

- **CSV formula injection.** Employee fields beginning with `= + - @` were
  written verbatim into credential and QR exports, where Excel evaluates them
  as formulas. All export paths now pass through `csv_safe()`.

- **XSS in job error rendering.** Server-controlled error strings were injected
  via `innerHTML`; they now use `textContent`.

- **Session cookie `Secure`** is applied whenever TLS is actually in use.
  (Forcing it on a plain-HTTP deployment simply breaks login — plaintext
  exposure is prevented by the startup refusal above instead.)

### Reliability — the "stuck loading" root cause

- **Cooperative cancellation.** The job watchdog only flipped a job's *state*
  to `timeout`; the worker thread stayed blocked inside `result = fn()`, so a
  large export kept running — holding SQLite locks and RAM — long after the UI
  reported a timeout. `job_should_stop()` / `job_checkpoint()` / `JobCancelled`
  are now wired into the export and provisioning loops, so a cancelled or
  timed-out operation actually stops.

- **Exports stream to disk.** `export_package()` and `bulk_provision()` built
  the entire archive in `io.BytesIO()`. They now write directly to
  `data/job_results/` and return a path.

- **Job results persist.** Results lived only in `JOBS[jid]['result']` in RAM,
  so a restart lost a finished export while the database still recorded
  success. Results are stored on disk with a SHA-256 checksum and served from
  there.

- **Backup creation streams.** `make_backup()` read each employee file fully
  into memory and then re-read the whole package for its checksum. Both are now
  chunked.

- **Retention and cleanup.** `audit`, `error_logs`, `security_login_events`,
  `system_sessions`, `device_events`, `notifications`, `bridge_tokens` and
  `auth_failures` all grew without bound. A daily retention pass now applies
  configurable horizons (audit never trimmed below one year). Orphaned
  `.tmp-*` / `.staging` artefacts from interrupted QR, export and backup runs
  are swept at startup and daily. In-memory caches are bounded.

### Operations

- **New health endpoints.**
  `/health/live` (process only — never fails on a locked DB),
  `/health/ready` (database reachable),
  `/health/deep` (authenticated: request p50/p95/p99, slow-request count,
  503/413 counts, SQLite lock waits and total lock seconds, DB size,
  `quick_check`, thread count, disk free, last backup age, encryption status).

- **`.env.example`** documents every configuration variable and which are
  secrets.

- `cryptography>=42.0` added to `requirements.txt` (backup encryption).

### Release hygiene

- Removed `accdb_raw_export.csv` (**404 real employee records**: names, badge
  numbers, departments) and added patterns to `.gitignore` that actually match
  it.
- Removed `data/hr_central.db` — a half-initialised database from an aborted
  test run (41 tables present, but no `employees`, `users` or `qr_identities`).
- Removed `server.py.bak`, all `__pycache__/` and `*.pyc`.
- Tests moved from the project root into `tests/{unit,integration,security,stress}/`.
- Five overlapping changelogs consolidated into this file.

### Known limitations

See `docs/KNOWN_LIMITATIONS.md`. In short: the monkey-patching architecture is
unchanged, CSP still requires `unsafe-inline`, and browser E2E / real ZKTeco
hardware / PostgreSQL end-to-end / large-dataset load testing have **not** been
performed.

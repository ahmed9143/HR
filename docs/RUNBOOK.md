# Production Runbook — HR Enterprise v17

Read this before installing, and again before your first restore drill.

---

## 1. The two keys — they are NOT interchangeable

The system generates **two separate 32-byte keys** on first run. They are kept
separate on purpose: rotating or losing one must not compromise the other.

| File | Purpose | If you lose it |
|---|---|---|
| `data/backup.key` | Encrypts backup archives (AES-256-GCM) | **Every encrypted backup becomes permanently unreadable.** There is no recovery path — this is what encryption means. |
| `data/secret.key` | Encrypts credentials stored in the database (currently ZKTeco device passwords) | Device passwords cannot be decrypted. The application still starts and all other data is intact; you re-enter each device password in the Devices screen. |

Both can be supplied from outside the data directory instead, which is the
better practice on a shared or backed-up volume:

```
HR_BACKUP_KEY=<base64 or 64 hex chars>
HR_SECRET_KEY=<base64 or 64 hex chars>
```

### Handover procedure

On delivery, and after any key rotation:

1. Copy **both** files to offline media (two copies, two locations).
2. Record which installation they belong to — keys are per-installation.
3. Store them separately from the backup archives. A key kept next to the
   backup it unlocks provides no protection.
4. Verify the copy: perform the restore drill in section 3 using only the
   copied key.

A backup whose key has never been used for a restore is an untested assumption.

---

## 2. What a backup contains

```
HR_Backup_<label>_<timestamp>.zip     (AES-256-GCM encrypted)
 ├── database.db          full SQLite database
 ├── employee_files/      uploaded documents and photos
 ├── qr/                  generated QR images
 ├── branding/            logo, ID-card template
 └── manifest.json        per-file size + SHA-256
```

**`qr/` and `branding/` were added in v17.** Any archive taken before that
contains only `database.db` and `employee_files/`. Restoring one will bring
back every QR *record* but no QR *image*, so ID cards render blank.

- Restoring an old archive **will not delete** the QR images you currently
  have — the restore leaves a tree alone when the archive does not carry it.
- After upgrading to v17, **take a fresh backup immediately**. Treat every
  pre-v17 archive as incomplete.

Backups are encrypted but **not immutable**. A compromised administrator
account or ransomware can still delete every copy. True immutability requires
an external target: a NAS snapshot, Windows Server Backup, or rotating offline
media. That is an operational requirement, not something the application can
provide by itself.

---

## 3. Restore drill

Do this once before go-live, and once a quarter afterwards. Never rehearse on
the production machine.

1. Take a backup from the Backups screen.
2. On a **separate** machine or folder, install the application fresh.
3. Copy in only two things: the backup archive and `data/backup.key`.
4. Start the application, log in, and restore from the Backups screen.
5. Verify: employee count, a specific employee's documents, QR images render,
   attendance for a known month, user accounts and roles.
6. Record how long steps 3–5 took. That is your real RTO.

`tests/dr/TEST_DISASTER_RECOVERY.py` automates this cycle and additionally
proves that a wrong key cannot decrypt, that a corrupted archive is rejected
before it overwrites anything, and that the restored database passes
`PRAGMA integrity_check`.

### Failure behaviour you should expect

| Situation | What happens |
|---|---|
| Wrong `backup.key` | Restore fails with a decryption error. Nothing is overwritten. |
| Corrupted archive | Rejected by manifest verification before extraction. |
| Archive containing `../` paths or symlinks | Rejected by `safe_extract_zip()` before a single byte is written. |
| Restored database fails `integrity_check` | Restore aborts; the live database is left untouched. |
| Archive predating v17 | Database and employee files restore; existing `qr/` and `branding/` are preserved rather than wiped. |

---

## 4. QR tokens: the legacy exposure

Databases created before the v17 security migration stored the QR **bearer
token in cleartext** in `qr_identities.token`. Three separate code paths wrote
it (single generation, bulk job, provisioning); all three are fixed, and a
startup migration redacts any value already stored.

Redaction removes the token from the database going forward. It does **not**
undo past exposure: anyone who obtained a copy of the old database file, or an
unencrypted backup of it, already has working tokens.

**If your installation ever ran a pre-v17 version, regenerate every QR code
after upgrading.** Bulk regeneration from the ID Cards screen issues fresh
tokens and invalidates the old ones. Until you do, assume the old badges are
compromised.

The same migration also finds QR rows marked active whose image file is
missing, and marks them `needs_regeneration` so bulk generation rebuilds them
instead of silently leaving a blank badge.

---

## 5. Bulk QR authorization

Bulk QR generation is controlled by one permission: **`qr.bulk_generate`**.

It is granted by default to `SuperAdmin`, `Admin` and `HR` — exactly the roles
that could already perform the operation before it became explicit, so
upgrading changes nothing for your users.

To restrict it to administrators: Roles screen → HR → uncheck
*توليد QR جماعي لكل الموظفين*. No code change, effective on the next request.

There is exactly one enforcement point (`stable_final`). A contradictory
`is_admin` guard that never executed was removed from `v13_security_ux`, so
the route cannot behave differently depending on import order.

Permission changes made through the Roles screen apply immediately. Changes
made **outside** the application — a direct database edit, a second process,
a restore — apply within the cache TTL (`HR_ROLE_PERMS_TTL`, default 60 s).

---

## 6. Windows deployment

The application targets Windows and is not validated on any other platform.

**File permissions.** `os.chmod(0o600)` does not produce a private file on
NTFS; it only toggles the read-only attribute. `protect_secret_file()` calls:

```
icacls <path> /inheritance:r /grant:r <CurrentUser>:F /grant:r Administrators:F
```

on `backup.key`, `secret.key` and `INITIAL_ADMIN_PASSWORD.txt`. It is
idempotent and logged. If `icacls` fails it prints a warning and continues —
deliberately, because locking the service out of its own key would be worse
than a loose ACL.

**This has not been verified on Windows.** Nothing in this project has been
executed on Windows; all measurements and test results come from Linux. After
deployment, confirm with `icacls data\backup.key` that inheritance is removed
and only the expected accounts are listed.

**Service account.** Run under a dedicated account, not an interactive admin
login. That account is the one that receives Full Control above.

---

## 7. TLS

`https_enabled=1` in the settings screen only adds an HSTS header and a Secure
cookie. It does **not** encrypt the connection.

For real HTTPS, set both:

```
HR_TLS_CERT=C:\hr\certs\server.pem
HR_TLS_KEY=C:\hr\certs\server.key
```

The server **refuses to start** when bound to a non-loopback address without
TLS. Override only with an HTTPS reverse proxy in front and
`HR_ALLOW_PLAINTEXT_LAN=1`, or on a physically isolated network.

Protect the private key with the same ACL treatment as the other secrets.

---

## 8. PostgreSQL

Not production-supported. See `docs/POSTGRES_STATUS.md`. `psycopg` is no longer
a mandatory dependency; SQLite is the only supported store.

---

## 9. ZKTeco devices

Device communication passwords are encrypted at rest (`enc:v1:` + AES-256-GCM,
using `secret.key`) and are never rendered back into the UI. The field shows an
empty password input; **leaving it blank on save keeps the existing password**.

Existing plaintext values are encrypted automatically on startup.

A password that cannot be decrypted raises an error at connect time rather than
falling back to an empty password. If that happens, `secret.key` is missing or
wrong — restore the key rather than re-entering passwords, or re-enter each
device password deliberately.

**No real device validation has been performed.** All ZKTeco testing used the
mock adapter. Before go-live, validate against one physical terminal: connect,
disconnect, employee sync, attendance download, reconnect, timeout, wrong
credentials, device offline.

---

## 10. Logs

Structured JSON, one object per line, at `data/logs/hr.log`, rotating at 5 MB
with 5 backups. Components: `startup, db, qr, job, backup, zkteco, auth, http, app`.

Any field whose name contains `password`, `token`, `secret`, `key`, `csrf` or
`cookie` is replaced with `***redacted***` before writing.

Set `HR_LOG_LEVEL=DEBUG` when diagnosing. `/health/deep` (authenticated) gives
request latency percentiles, SQLite lock waits, thread count, disk free and
backup age — use it before guessing at a performance problem.

---

## 11. Known operational issue: first-request latency

At 5,000 employees the dashboard's **first** request after a large data change
takes roughly 4 seconds; every subsequent request takes about 16 ms. Users
experience this as a freeze the first time they open the system each morning.

The root cause has not been identified. Do not paper over it with a startup
warm-up: that hides the work rather than removing it, and it returns after any
large import or attendance sync.

---

## 12. Pre-go-live checklist

- [ ] Both keys copied to offline media, in two locations
- [ ] Restore drill completed on a separate machine, RTO recorded
- [ ] Fresh post-v17 backup taken; pre-v17 archives marked incomplete
- [ ] All QR codes regenerated if the installation ever ran a pre-v17 version
- [ ] `qr.bulk_generate` reviewed against your policy for the HR role
- [ ] TLS certificate installed, or reverse proxy in place
- [ ] `icacls` output verified on both key files
- [ ] Dedicated service account configured
- [ ] One physical ZKTeco device validated end to end
- [ ] Full test suite executed **on Windows**
- [ ] Backup schedule and retention confirmed, including an offline tier

---

## 13. Offline backup tier — the part the application cannot do for you

Backups are encrypted and verified, but they are **not immutable**. Every copy
the application knows about can be deleted by the same administrator account —
or by ransomware running as that account. Encryption protects confidentiality;
it does nothing for availability.

Real immutability needs a target the application cannot reach. Pick one:

| Option | How it resists deletion |
|---|---|
| Rotating offline USB/disk | Physically disconnected between rotations |
| NAS snapshots | Snapshots are taken and retained by the NAS, not the client |
| Windows Server Backup to a separate volume | Separate credentials, separate retention |
| Cloud object storage with an immutability/lock policy | The provider refuses deletion until the lock expires |

### Minimum viable procedure

1. Weekly, copy the newest `data/backups/HR_Backup_*.zip` to offline media.
2. Keep **four** weekly copies plus **one** monthly copy.
3. Store the media in a different physical location from the server.
4. Keep `backup.key` with neither the server nor the backup media — a key
   stored beside the archive it unlocks provides no protection.
5. Once a quarter, restore one offline copy on a spare machine and confirm
   employee count, documents, QR images and attendance. Record the elapsed
   time: that is your real RTO.

### Verifying a copy before you trust it

```
python - <<'PY'
import sys; sys.path.insert(0, r"C:\path\to\hr")
import os; os.environ["HR_DATA_DIR"] = r"C:\path\to\hr\data"
import server as S
ok, msg = S.verify_backup_package(r"E:\offline\HR_Backup_weekly_20260912.zip")
print("USABLE" if ok else "DO NOT TRUST", msg)
PY
```

This decrypts with the configured key and checks every file against the
manifest checksums. A copy that has never been verified is an assumption, not
a backup.

### What the application does enforce

- Every archive is AES-256-GCM encrypted; tampering fails the GCM tag.
- `verify_backup_package()` checks per-file SHA-256 against the manifest.
- Restore refuses a corrupt archive, a wrong key, path traversal, symlinks and
  zip bombs, and it verifies the restored database with `PRAGMA integrity_check`
  **before** replacing the live one.
- An archive that predates v17 will not delete the QR images you currently have.

None of that survives someone deleting every copy. That is why the offline tier
is an operational requirement, not a feature request.

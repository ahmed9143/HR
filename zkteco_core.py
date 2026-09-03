# ZKTeco Integration — Phase 1 (Database / Schema foundation only).
#
# Scope lock for this phase: schema + migration + validation ONLY.
# Explicitly NOT included here: pyzk / any device connection, background sync
# service, backup-file parser, Sidebar UI, employee-mapping UI, permissions
# (zkteco.manage/zkteco.sync/zkteco.mapping are deferred to a later phase).
#
# NOTE on employees.zk_user_id: that column (and its partial unique index) is
# added inside server.py's own _init_db_schema(), next to its existing
# self-healing `extra_cols` block for the employees table -- NOT here. Every
# install_vX(globals()) call, including this module's, runs at import time,
# before _init_db_schema()/init()/main() ever execute (main() is only invoked
# by the very last line of server.py). On a brand-new install the employees
# table does not exist yet at that point, so an ALTER TABLE employees here
# would fail on first run. _init_db_schema() is the only place in the startup
# sequence guaranteed to run after employees already exists, so that's where
# the column belongs. This module only owns tables that don't depend on
# employees/attendance existing at creation time.
#
# Design summary (see chat history for full rationale):
#   - employees.zk_user_id is the single source of truth for the
#     employee <-> ZKTeco identity link. One employee = one zk_user_id,
#     shared across any number of physical devices. employees.fingerprint
#     is untouched (it is dead code elsewhere in the app; not reused,
#     not renamed, not migrated).
#   - zk_attendance_raw stores punches exactly as they arrive from a
#     device: device_id + zk_user_id only. No emp_code is stored on the
#     raw row, so a later change to an employee's mapping never rewrites
#     history. Matching to an employee happens at processing time via a
#     join against employees.zk_user_id (a future phase).
#   - Deduplication is intentionally NOT finalized in this phase: the
#     record_uid column exists so a hardware transaction id can be used
#     once Phase 2 confirms what the connector library actually provides.
#     Only a non-unique lookup index is added now; a strict dedup
#     constraint is additive later and is not a destructive migration.
#   - zk_unmatched only tracks unresolved zk_user_ids; it never creates
#     an employee automatically. zk_name_raw (here and in zk_unmatched)
#     is for display/diagnostics only and is never used for matching.
#   - attendance (existing daily-summary table) is not touched at all.
#
# Migration style matches the rest of the project (see enterprise_completion.py):
# CREATE TABLE IF NOT EXISTS, idempotent, additive-only, safe to run on every
# startup, and works unmodified against both SQLite and PostgreSQL (via
# pg_compat.py). No new third-party dependency is introduced.

ZK_PHASE = '1 (schema-only)'


def install_zkteco(g):
    db = g['db']

    c = db()
    try:
        # All zk_-prefixed to avoid any collision with the existing device_trust /
        # device_events / sync_queue tables, which belong to an unrelated
        # LAN-discovery / server-trust feature and are not touched here. None of
        # these reference employees/attendance at creation time (no FK), so they
        # are safe to create regardless of whether the core schema has run yet.
        c.executescript('''
        CREATE TABLE IF NOT EXISTS zk_devices(
            id INTEGER PRIMARY KEY,
            device_key TEXT UNIQUE,
            name TEXT,
            location TEXT,
            ip TEXT,
            port INTEGER DEFAULT 4370,
            comm_password TEXT DEFAULT '',
            timeout_seconds INTEGER DEFAULT 10,
            active INTEGER DEFAULT 1,
            status TEXT DEFAULT 'unknown',
            last_seen TEXT,
            last_sync_at TEXT,
            created_by TEXT,
            created_at TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS zk_attendance_raw(
            id INTEGER PRIMARY KEY,
            device_id TEXT NOT NULL,
            zk_user_id TEXT NOT NULL,
            punch_time TEXT NOT NULL,
            verify_type INTEGER,
            punch_state INTEGER,
            record_uid TEXT,
            raw_payload TEXT,
            match_status TEXT DEFAULT 'pending',
            processed INTEGER DEFAULT 0,
            processed_at TEXT,
            created_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_zk_raw_lookup ON zk_attendance_raw(device_id, zk_user_id, punch_time);
        CREATE INDEX IF NOT EXISTS idx_zk_raw_processed ON zk_attendance_raw(processed);

        CREATE TABLE IF NOT EXISTS zk_sync_logs(
            id INTEGER PRIMARY KEY,
            device_id TEXT,
            sync_type TEXT,
            started_at TEXT,
            finished_at TEXT,
            status TEXT DEFAULT 'running',
            fetched_count INTEGER DEFAULT 0,
            new_count INTEGER DEFAULT 0,
            duplicate_count INTEGER DEFAULT 0,
            unmatched_count INTEGER DEFAULT 0,
            failed_count INTEGER DEFAULT 0,
            error_message TEXT,
            triggered_by TEXT,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS zk_unmatched(
            id INTEGER PRIMARY KEY,
            device_id TEXT,
            zk_user_id TEXT,
            zk_name_raw TEXT,
            first_seen TEXT,
            last_seen TEXT,
            punch_count INTEGER DEFAULT 0,
            status TEXT DEFAULT 'open',
            resolved_emp_code TEXT,
            resolved_by TEXT,
            resolved_at TEXT,
            UNIQUE(device_id, zk_user_id)
        );
        ''')
        c.commit()
    finally:
        c.close()

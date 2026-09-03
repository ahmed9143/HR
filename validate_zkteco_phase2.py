"""
Offline validation for ZKTeco Phase 2 (connector + sync engine).
Uses MockZKAdapter only -- no real device/network required.

Run: python3 validate_zkteco_phase2.py
"""
import os, sys, sqlite3, tempfile, shutil

RESULTS = []
def check(name, cond):
    RESULTS.append((name, bool(cond)))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")

def main():
    workdir = tempfile.mkdtemp(prefix="zk_phase2_")
    dbpath = os.path.join(workdir, "hr_test.db")
    os.environ['HR_DATA_DIR'] = workdir
    os.environ['HR_DB_PATH'] = dbpath  # in case server.py honors this; harmless if not

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    # Build a minimal pre-existing DB the way server.py's own schema would,
    # then let server.py's import-time migrations run on top of it, exactly
    # like Phase 1's validator did.
    conn = sqlite3.connect(dbpath)
    conn.execute("CREATE TABLE employees (emp_code TEXT PRIMARY KEY, name TEXT, fingerprint TEXT)")
    conn.execute("INSERT INTO employees (emp_code, name) VALUES ('E1','Ahmed')")
    conn.execute("INSERT INTO employees (emp_code, name) VALUES ('E2','Sara')")
    conn.commit()
    conn.close()

    # Point server.py at this DB file the same way the Phase 1 validator did:
    # patch DB path before import via monkeypatch of the module-level constant
    # is not possible pre-import, so we replicate Phase 1's approach: import
    # server with DB var overridden immediately after import, then re-run the
    # schema init explicitly.
    import importlib
    global server
    import server as server  # triggers install_zkteco + install_zkteco_sync at import time
    server.DB = dbpath
    server._init_db_schema()  # ensure employees.zk_user_id / index exist against this DB

    # zk_* tables were created at import time against the *default* DB path
    # (module import happens before we can patch DB). Re-run both installers
    # now that server.DB points at our test DB, same as the Phase 1 validator
    # had to do for the same reason.
    import zkteco_core as _zc
    import zkteco_sync as _zs
    _zc.install_zkteco(server.__dict__)
    _zs.install_zkteco_sync(server.__dict__)

    # Link one employee to a zk_user_id so we can test matched vs unmatched.
    c = server.db()
    c.execute("UPDATE employees SET zk_user_id='1001' WHERE emp_code='E1'")
    c.commit()
    c.close()

    from zkteco_connector import MockZKAdapter
    from zkteco_sync import sync_device

    device_id = 'dev-test-1'

    # --- Run 1: first sync ---
    adapter = MockZKAdapter(ip="10.0.0.50")
    summary1 = sync_device(server.__dict__, device_id, adapter, triggered_by='validator')
    check("first sync status=success", summary1['status'] == 'success')
    check("first sync fetched=4 (mock dataset size)", summary1['fetched'] == 4)
    check("first sync new=4 (nothing pre-existing)", summary1['new'] == 4)
    check("first sync duplicate=0", summary1['duplicate'] == 0)
    # E2 has no zk_user_id set, so mock user '1002' is unmatched too, plus '9999' -> 2 distinct unmatched punches
    check("first sync unmatched=2 (zk_user_ids 1002 and 9999 have no employee)", summary1['unmatched'] == 2)

    # --- Run 2: same data again -> must be fully deduped, not partial ---
    adapter2 = MockZKAdapter(ip="10.0.0.50")
    summary2 = sync_device(server.__dict__, device_id, adapter2, triggered_by='validator')
    check("second sync status=success", summary2['status'] == 'success')
    check("second sync new=0 (full dedup)", summary2['new'] == 0)
    check("second sync duplicate=4 (all previously seen)", summary2['duplicate'] == 4)

    c = server.db()
    row_count = c.execute("SELECT COUNT(*) n FROM zk_attendance_raw").fetchone()['n']
    check("zk_attendance_raw has exactly 4 rows after 2 syncs (no duplication)", row_count == 4)

    matched_row = c.execute(
        "SELECT match_status FROM zk_attendance_raw WHERE zk_user_id='1001' LIMIT 1"
    ).fetchone()
    check("matched punch has match_status='matched'", matched_row and matched_row['match_status'] == 'matched')

    unmatched_row = c.execute(
        "SELECT match_status FROM zk_attendance_raw WHERE zk_user_id='9999' LIMIT 1"
    ).fetchone()
    check("unmatched punch has match_status='unmatched'", unmatched_row and unmatched_row['match_status'] == 'unmatched')

    zku = c.execute("SELECT * FROM zk_unmatched WHERE device_id=? AND zk_user_id='9999'", (device_id,)).fetchone()
    check("zk_unmatched has exactly one row for 9999", zku is not None)
    check("zk_unmatched punch_count=1 after 2 syncs (2nd sync is all duplicates, count must not inflate)", zku['punch_count'] == 1)

    logs = c.execute("SELECT COUNT(*) n FROM zk_sync_logs WHERE device_id=?", (device_id,)).fetchone()['n']
    check("zk_sync_logs has 2 rows (one per sync call)", logs == 2)

    # --- employees/attendance integrity: untouched by sync ---
    emp_count = c.execute("SELECT COUNT(*) n FROM employees").fetchone()['n']
    check("employees count unchanged (still 2)", emp_count == 2)
    e1 = c.execute("SELECT zk_user_id FROM employees WHERE emp_code='E1'").fetchone()
    check("E1.zk_user_id still '1001' (not overwritten by sync)", e1['zk_user_id'] == '1001')
    fp_col_exists = 'fingerprint' in [r[1] for r in c.execute("PRAGMA table_info(employees)").fetchall()]
    check("employees.fingerprint column untouched/still exists", fp_col_exists)

    # --- dedup index actually enforces uniqueness at the DB level ---
    try:
        c.execute(
            "INSERT INTO zk_attendance_raw (device_id, zk_user_id, punch_time, record_uid, match_status, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (device_id, '1001', '2026-08-20T08:01:00',
             c.execute("SELECT record_uid FROM zk_attendance_raw WHERE zk_user_id='1001' LIMIT 1").fetchone()['record_uid'],
             'matched', server.now())
        )
        c.commit()
        check("DB-level UNIQUE index rejects duplicate record_uid", False)
    except sqlite3.IntegrityError:
        check("DB-level UNIQUE index rejects duplicate record_uid", True)
        c.rollback()

    # --- adapter connection-failure path doesn't crash sync_device ---
    from zkteco_connector import MockZKAdapter as MZ
    bad_adapter = MZ(ip="10.0.0.99", fail_connect=True)
    summary3 = sync_device(server.__dict__, 'dev-offline', bad_adapter, triggered_by='validator')
    check("sync against unreachable device returns status=failed (no crash)", summary3['status'] == 'failed')
    check("failed sync still writes a zk_sync_logs row", 
          c.execute("SELECT COUNT(*) n FROM zk_sync_logs WHERE device_id='dev-offline'").fetchone()['n'] == 1)

    c.close()

    # --- idempotent module install (call twice in fresh process-like calls) ---
    from zkteco_sync import install_zkteco_sync
    try:
        install_zkteco_sync(server.__dict__)
        install_zkteco_sync(server.__dict__)
        check("install_zkteco_sync is idempotent (runs twice without error)", True)
    except Exception as e:
        check(f"install_zkteco_sync idempotent -- FAILED: {e}", False)

    shutil.rmtree(workdir, ignore_errors=True)

    passed = sum(1 for _, ok in RESULTS if ok)
    total = len(RESULTS)
    print(f"\n{passed}/{total} PASS")
    if passed != total:
        sys.exit(1)

if __name__ == '__main__':
    main()

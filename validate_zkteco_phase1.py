"""
ZKTeco Phase 1 — standalone validation script.

Run this AFTER dropping zkteco_core.py into the project and applying the
server.py changes, and AFTER starting the app once (or calling server.init())
so the migration has actually executed.

Strongly recommended: point HR_DATA_DIR at a COPY of your data folder first,
not the live production one, e.g.:

    cp -r "C:\\ProgramData\\HR Enterprise\\Data" C:\\temp\\hr_data_copy
    set HR_DATA_DIR=C:\\temp\\hr_data_copy
    python validate_zkteco_phase1.py

The script only performs temporary, self-cleaning writes (a couple of test
employee rows it deletes at the end) to prove the constraints behave
correctly — it never touches your real employee/attendance rows.

Usage:
    HR_DATA_DIR=/path/to/data python validate_zkteco_phase1.py
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402

results = []


def check(name, cond, detail=""):
    results.append((name, "PASS" if cond else "FAIL", detail))


def main():
    # Make sure the schema/migration has actually run (idempotent — safe on an
    # already-migrated DB too).
    server.init()

    c = server.db()

    # --- existing data safety -------------------------------------------------
    emp_count = c.execute("SELECT COUNT(*) n FROM employees").fetchone()["n"]
    att_count = c.execute("SELECT COUNT(*) n FROM attendance").fetchone()["n"]
    check("employees table readable", True, f"count={emp_count}")
    check("attendance table readable", True, f"count={att_count}")

    fp_cols = {r["name"] for r in c.execute("PRAGMA table_info(employees)").fetchall()}
    check("employees.fingerprint column still present (untouched)", "fingerprint" in fp_cols)

    # --- new column -------------------------------------------------------------
    check("employees.zk_user_id column exists", "zk_user_id" in fp_cols)

    existing_zk = [r["zk_user_id"] for r in c.execute("SELECT zk_user_id FROM employees").fetchall()]
    check(
        "zk_user_id is NULL for all pre-existing employees (no forced backfill)",
        all(v is None for v in existing_zk),
    )

    # --- NULL / UNIQUE behaviour (self-cleaning test rows) -----------------------
    test_codes = ["__ZK_PHASE1_TEST_A__", "__ZK_PHASE1_TEST_B__"]
    try:
        c.execute("DELETE FROM employees WHERE emp_code IN (?,?)", test_codes)
        c.commit()

        c.execute("INSERT INTO employees(emp_code,name) VALUES(?,?)", (test_codes[0], "Phase1 Test A"))
        c.execute("INSERT INTO employees(emp_code,name) VALUES(?,?)", (test_codes[1], "Phase1 Test B"))
        c.commit()
        check("insert employees with NULL zk_user_id succeeds", True)

        c.execute("UPDATE employees SET zk_user_id='__ZK_TEST_9999__' WHERE emp_code=?", (test_codes[0],))
        c.commit()
        check("assigning a zk_user_id succeeds", True)

        dup_rejected = False
        try:
            c.execute("UPDATE employees SET zk_user_id='__ZK_TEST_9999__' WHERE emp_code=?", (test_codes[1],))
            c.commit()
        except Exception:
            dup_rejected = True
            c.rollback()
        check("duplicate zk_user_id is rejected", dup_rejected)
    finally:
        c.execute("DELETE FROM employees WHERE emp_code IN (?,?)", test_codes)
        c.commit()

    # --- new zk_ tables -----------------------------------------------------------
    expected = {
        "zk_devices": {"id", "device_key", "name", "location", "ip", "port", "comm_password",
                        "timeout_seconds", "active", "status", "last_seen", "last_sync_at",
                        "created_by", "created_at", "updated_at"},
        "zk_attendance_raw": {"id", "device_id", "zk_user_id", "punch_time", "verify_type",
                               "punch_state", "record_uid", "raw_payload", "match_status",
                               "processed", "processed_at", "created_at"},
        "zk_sync_logs": {"id", "device_id", "sync_type", "started_at", "finished_at", "status",
                          "fetched_count", "new_count", "duplicate_count", "unmatched_count",
                          "failed_count", "error_message", "triggered_by", "created_at"},
        "zk_unmatched": {"id", "device_id", "zk_user_id", "zk_name_raw", "first_seen", "last_seen",
                          "punch_count", "status", "resolved_emp_code", "resolved_by", "resolved_at"},
    }
    for table, cols in expected.items():
        exists = c.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone() is not None
        if exists:
            actual = {r["name"] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}
            check(f"{table} exists with expected columns", cols.issubset(actual), f"missing={cols - actual}")
        else:
            check(f"{table} exists with expected columns", False, "table missing")

    check(
        "zk_attendance_raw has no emp_code column (matching deferred to processing phase)",
        "emp_code" not in {r["name"] for r in c.execute("PRAGMA table_info(zk_attendance_raw)").fetchall()},
    )

    # --- unrelated tables untouched ------------------------------------------------
    for t in ("device_trust", "device_events", "sync_queue"):
        exists = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone() is not None
        check(f"unrelated table {t} present (not touched, no zk_ collision)", exists)

    c.close()

    print(json.dumps(results, ensure_ascii=False, indent=2))
    n_fail = sum(1 for _, s, _ in results if s == "FAIL")
    print(f"\nTOTAL: {len(results)}  PASS: {len(results) - n_fail}  FAIL: {n_fail}")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()

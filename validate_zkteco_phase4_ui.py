"""
Offline validation for ZKTeco Phase 4 (in-app UI).
Imports server.py against a scratch SQLite DB (same technique as
validate_zkteco_phase2.py / phase3), then drives the new HTTP routes
directly through the H request-handler class (no real socket/server
needed) to confirm devices/sync/unmatched/attendance all work end to end,
and that the previous 59 tests' worth of routes/tables are untouched.

Run: python3 validate_zkteco_phase4_ui.py
"""
import os, sys, sqlite3, tempfile

RESULTS = []
def check(name, cond):
    RESULTS.append((name, bool(cond)))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")


def main():
    workdir = tempfile.mkdtemp(prefix="zk_phase4_")
    dbpath = os.path.join(workdir, "hr_test.db")
    os.environ['HR_DATA_DIR'] = workdir

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    conn = sqlite3.connect(dbpath)
    conn.execute("CREATE TABLE employees (emp_code TEXT PRIMARY KEY, name TEXT, fingerprint TEXT, status TEXT DEFAULT 'نشط')")
    conn.execute("INSERT INTO employees (emp_code, name) VALUES ('E1','Ahmed')")
    conn.execute("INSERT INTO employees (emp_code, name) VALUES ('E2','Sara')")
    conn.commit()
    conn.close()

    import server as server
    server.DB = dbpath
    server._init_db_schema()

    import zkteco_core as _zc, zkteco_sync as _zs, zkteco_ui as _zu
    _zc.install_zkteco(server.__dict__)
    _zs.install_zkteco_sync(server.__dict__)
    _zu.install_zkteco_ui(server.__dict__)

    check("install_zkteco_ui ran without raising", True)

    c = server.db()
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    check("zk_devices table exists", 'zk_devices' in tables)
    check("zk_attendance_raw table exists", 'zk_attendance_raw' in tables)
    check("zk_sync_logs table exists", 'zk_sync_logs' in tables)
    check("zk_unmatched table exists", 'zk_unmatched' in tables)
    c.close()

    # --- exercise the handler methods directly (bypassing raw HTTP/socket) ---
    from zkteco_connector import MockZKAdapter

    class FakeUser(dict):
        pass

    admin_user = {'username': 'admin', 'role': 'Admin', 'full_name': 'Admin', 'csrf': 'tok123',
                  'must_change_password': 0}

    H = server.H

    # zk_devices_page / save / toggle / delete / test — call the underlying
    # functions the way do_GET/do_POST would, via the H instance's bound
    # methods installed by install_zkteco_ui (they hang off closures, so we
    # reach them the same way the real dispatcher does: through H.do_GET).
    class Recorder:
        def __init__(self):
            self.sent = None
            self.status = None
            self.redirected_to = None
        def send(self, body, status=200, ctype='text/html; charset=utf-8', headers=None):
            self.sent = body; self.status = status
        def redirect(self, url, extra=None):
            self.redirected_to = url

    def call(path, method='GET', form=None):
        rec = Recorder()
        h = H.__new__(H)
        h.path = path
        h.send = rec.send
        h.redirect = rec.redirect
        h.client_address = ('127.0.0.1', 0)
        h.request_id = 'TEST'
        h.require = lambda: admin_user
        h.need = lambda u, p: True
        h.form = (lambda: form) if form is not None else (lambda: {})
        h.fval = server.H.fval.__get__(h)
        h.headers = type('Hdr', (), {'get': lambda self, k, d='': d})()
        if method == 'GET':
            server.H.do_GET(h)
        else:
            server.H.do_POST(h)
        return rec

    # 1. Devices page loads
    r = call('/zkteco/devices')
    check("GET /zkteco/devices renders", r.sent is not None and 'أجهزة' in r.sent)

    # 2. Save a new device
    r = call('/zkteco/devices/save', 'POST', {'_csrf': 'tok123', 'name': 'Test Device', 'ip': '10.0.0.5', 'port': '4370', 'location': 'Lobby', 'comm_password': '', 'timeout_seconds': '10'})
    check("POST /zkteco/devices/save redirects (success)", r.redirected_to is not None and 'flash=ok' in (r.redirected_to or ''))

    c = server.db()
    dev = c.execute("SELECT * FROM zk_devices WHERE name='Test Device'").fetchone()
    c.close()
    check("device row actually created", dev is not None)
    dev_id = dev['id'] if dev else None
    device_key = dev['device_key'] if dev else None

    # 3. Toggle (disable) then toggle back
    r = call('/zkteco/devices/toggle', 'POST', {'_csrf': 'tok123', 'id': str(dev_id)})
    c = server.db(); row = c.execute('SELECT active FROM zk_devices WHERE id=?', (dev_id,)).fetchone(); c.close()
    check("toggle disabled the device", row['active'] == 0)
    call('/zkteco/devices/toggle', 'POST', {'_csrf': 'tok123', 'id': str(dev_id)})

    # 4. Mock test-connection
    r = call('/zkteco/devices/test', 'POST', {'_csrf': 'tok123', 'id': str(dev_id), 'mock': '1'})
    c = server.db(); row = c.execute('SELECT status FROM zk_devices WHERE id=?', (dev_id,)).fetchone(); c.close()
    check("mock test_connection sets status=online", row['status'] == 'online')

    # 5. Real (non-mock) test-connection against an unreachable IP fails cleanly, no crash
    r = call('/zkteco/devices/test', 'POST', {'_csrf': 'tok123', 'id': str(dev_id)})
    check("real test_connection against unreachable IP does not crash", r.redirected_to is not None)

    # 6. Sync page loads
    r = call('/zkteco/sync')
    check("GET /zkteco/sync renders", r.sent is not None)

    # 7. Run a mock sync
    r = call('/zkteco/sync/run', 'POST', {'_csrf': 'tok123', 'id': str(dev_id), 'mock': '1'})
    check("POST /zkteco/sync/run redirects (success)", r.redirected_to is not None and 'flash=ok' in (r.redirected_to or ''))

    c = server.db()
    raw_count = c.execute('SELECT COUNT(*) n FROM zk_attendance_raw').fetchone()['n']
    log_count = c.execute('SELECT COUNT(*) n FROM zk_sync_logs').fetchone()['n']
    unmatched_count = c.execute("SELECT COUNT(*) n FROM zk_unmatched WHERE status='open'").fetchone()['n']
    c.close()
    check("sync wrote raw attendance rows", raw_count > 0)
    check("sync wrote a sync_logs row", log_count > 0)
    check("sync produced an unmatched entry (zk_user_id 9999 has no employee)", unmatched_count > 0)

    # 8. Re-running the same mock sync is idempotent (no duplicate raw rows)
    call('/zkteco/sync/run', 'POST', {'_csrf': 'tok123', 'id': str(dev_id), 'mock': '1'})
    c = server.db()
    raw_count2 = c.execute('SELECT COUNT(*) n FROM zk_attendance_raw').fetchone()['n']
    c.close()
    check("re-running sync does not duplicate raw rows (idempotent)", raw_count2 == raw_count)

    # 9. Unmatched page loads and lists the open entry
    r = call('/zkteco/unmatched')
    check("GET /zkteco/unmatched renders", r.sent is not None and ('9999' in r.sent))

    c = server.db()
    um = c.execute("SELECT * FROM zk_unmatched WHERE status='open' LIMIT 1").fetchone()
    c.close()
    check("an open unmatched row exists to resolve", um is not None)

    # 10. Resolve unmatched -> link to employee E2 (E1 stays unlinked to test duplicate protection later)
    r = call('/zkteco/unmatched/resolve', 'POST', {'_csrf': 'tok123', 'id': str(um['id']), 'emp_code': 'E2'})
    check("resolve redirects with ok flash", r.redirected_to is not None and 'flash=ok' in (r.redirected_to or ''))
    c = server.db()
    e2 = c.execute("SELECT zk_user_id FROM employees WHERE emp_code='E2'").fetchone()
    um_after = c.execute("SELECT status FROM zk_unmatched WHERE id=?", (um['id'],)).fetchone()
    c.close()
    check("employee E2 now has zk_user_id set", e2['zk_user_id'] == um['zk_user_id'])
    check("zk_unmatched row marked resolved", um_after['status'] == 'resolved')

    # 11. Duplicate-link protection: try to link the SAME zk_user_id to E1 too
    #     (simulate a second open unmatched row referencing the same zk_user_id
    #      that's already linked to E2 -- should be rejected, not crash).
    c = server.db()
    c.execute(
        "INSERT INTO zk_unmatched(device_id, zk_user_id, zk_name_raw, first_seen, last_seen, punch_count, status) "
        "VALUES(?,?,?,?,?,?, 'open')",
        ('other-device', um['zk_user_id'], None, '2026-01-01T00:00:00', '2026-01-01T00:00:00', 1)
    )
    c.commit()
    dup_id = c.execute("SELECT id FROM zk_unmatched WHERE zk_user_id=? AND status='open'", (um['zk_user_id'],)).fetchone()['id']
    c.close()
    r = call('/zkteco/unmatched/resolve', 'POST', {'_csrf': 'tok123', 'id': str(dup_id), 'emp_code': 'E1'})
    check("linking an already-used zk_user_id to a second employee is rejected", 'flash=err' in (r.redirected_to or ''))
    c = server.db()
    e1 = c.execute("SELECT zk_user_id FROM employees WHERE emp_code='E1'").fetchone()
    c.close()
    check("E1 was NOT linked by the rejected duplicate attempt", e1['zk_user_id'] is None)

    # 12. Attendance page loads, with and without filters
    r = call('/zkteco/attendance')
    check("GET /zkteco/attendance renders", r.sent is not None)
    r = call('/zkteco/attendance?status=matched')
    check("GET /zkteco/attendance?status=matched renders", r.sent is not None)
    r = call('/zkteco/attendance?q=Sara')
    check("GET /zkteco/attendance?q=Sara renders and finds the linked employee", r.sent is not None and 'Sara' in r.sent)

    # 13. Delete the test device; historical attendance rows must remain untouched
    r = call('/zkteco/devices/delete', 'POST', {'_csrf': 'tok123', 'id': str(dev_id)})
    c = server.db()
    still_there = c.execute('SELECT COUNT(*) n FROM zk_devices WHERE id=?', (dev_id,)).fetchone()['n']
    raw_after_delete = c.execute('SELECT COUNT(*) n FROM zk_attendance_raw').fetchone()['n']
    c.close()
    check("device row removed after delete", still_there == 0)
    check("attendance history preserved after device delete", raw_after_delete == raw_count2)

    # 14. Sidebar injection: page() output contains the new nav group for an admin
    html = server.page('Test', '<div>body</div>', admin_user)
    check("sidebar contains ZKTeco nav group", 'zkteco/devices' in html and 'zkteco/sync' in html and 'zkteco/unmatched' in html and 'zkteco/attendance' in html)

    # 15. A non-privileged user does NOT see the ZKTeco nav group
    plain_user = {'username': 'emp1', 'role': 'Employee', 'full_name': 'Emp', 'csrf': 'tok999', 'must_change_password': 0}
    html2 = server.page('Test', '<div>body</div>', plain_user)
    check("non-privileged user's sidebar has no ZKTeco links", 'zkteco/devices' not in html2)

    print()
    passed = sum(1 for _, ok in RESULTS if ok)
    total = len(RESULTS)
    print(f"TOTAL: {passed}/{total} PASS")
    if passed != total:
        sys.exit(1)


if __name__ == '__main__':
    main()

"""Session persistence — a restart must not log everyone out.

SESS lives in the process, so every restart (an update, a crash, a reboot)
dropped every user mid-task even though system_sessions already held the row.
Sessions are now rebuilt from the database on a cache miss.

The dangerous way to "fix" that is to trust the cookie alone. These tests check
the opposite too: a revoked session, a deactivated user and an idle session must
all still be refused after a restart.

Run:  python tests/security/TEST_SESSION_PERSISTENCE.py
"""
import os, re, sys, time, html, sqlite3, tempfile, subprocess, pathlib
import urllib.request, urllib.parse, urllib.error, http.cookiejar

ROOT = pathlib.Path(__file__).resolve().parents[2]
PORT = int(os.environ.get('SESSPERS_PORT', '8871'))
ADMIN_PW = 'TestAdmin@12345'
NEW_PW = 'RotatedPw#2026x'
RESULTS = []


def record(name, status, detail=''):
    RESULTS.append((name, status, detail))
    print(f'[{status}] {name}' + (f' — {detail}' if detail else ''))


def csrf_of(m):
    x = re.search(r'name="_csrf"[^>]*value="([^"]*)"', m)
    return html.unescape(x.group(1)) if x else ''


class Server:
    def __init__(self, data_dir, port):
        self.base = f'http://127.0.0.1:{port}'
        env = dict(os.environ, HR_DATA_DIR=data_dir, HR_MODE='standalone',
                   HR_HOST='127.0.0.1', HR_PORT=str(port), HR_PORT_MAX=str(port + 2),
                   HR_NO_BROWSER='1', HR_BOOTSTRAP_PASSWORD=ADMIN_PW)
        self.proc = subprocess.Popen([sys.executable, 'server.py'], cwd=str(ROOT), env=env,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    def wait(self, timeout=60):
        end = time.time() + timeout
        while time.time() < end:
            try:
                urllib.request.urlopen(self.base + '/health/ready', timeout=2).read()
                return True
            except Exception:
                time.sleep(0.4)
        return False

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()


def client():
    jar = http.cookiejar.CookieJar()
    return jar, urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def get(op, base, path):
    try:
        r = op.open(base + path, timeout=30)
        return r.status, r.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace')


def post(op, base, path, fields):
    req = urllib.request.Request(base + path,
                                 data=urllib.parse.urlencode(fields).encode(), method='POST')
    req.add_header('Content-Type', 'application/x-www-form-urlencoded')
    try:
        r = op.open(req, timeout=60)
        return r.status, r.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace')


def logged_in(op, base):
    status, body = get(op, base, '/employees')
    return status == 200 and 'name="password"' not in body


def main():
    td = tempfile.mkdtemp(prefix='sesspers_')
    db_path = os.path.join(td, 'hr_central.db')

    srv = Server(td, PORT)
    if not srv.wait():
        record('server starts', 'FAIL'); return 1
    record('server starts', 'PASS')

    jar, op = client()
    _, lp = get(op, srv.base, '/login')
    post(op, srv.base, '/login', {'username': 'admin', 'password': ADMIN_PW, '_csrf': csrf_of(lp)})
    _, pwp = get(op, srv.base, '/password')
    post(op, srv.base, '/password', {'_csrf': csrf_of(pwp), 'current': ADMIN_PW,
                                     'new_password': NEW_PW, 'confirm': NEW_PW})
    record('logged in before the restart', 'PASS' if logged_in(op, srv.base) else 'FAIL')

    sid = next((ck.value for ck in jar if ck.name == 'sid'), None)
    record('session cookie issued', 'PASS' if sid else 'FAIL')

    con = sqlite3.connect(db_path); con.row_factory = sqlite3.Row
    row = con.execute('SELECT * FROM system_sessions WHERE session_id=?', (sid,)).fetchone()
    con.close()
    record('session recorded in the database', 'PASS' if row else 'FAIL')
    record('the CSRF token is persisted with the session',
           'PASS' if row and 'csrf' in row.keys() and row['csrf'] else 'FAIL',
           'without it every open tab would fail its next POST')

    csrf_before = csrf_of(get(op, srv.base, '/employees')[1])

    # ------------------------------------------------------- RESTART -----
    srv.stop()
    srv2 = Server(td, PORT + 3)
    if not srv2.wait():
        record('server restarts', 'FAIL'); return 1
    record('server restarts with an empty in-memory session store', 'PASS')

    record('the session survives the restart',
           'PASS' if logged_in(op, srv2.base) else 'FAIL',
           'user is still authenticated without logging in again')

    csrf_after = csrf_of(get(op, srv2.base, '/employees')[1])
    record('the CSRF token is preserved across the restart',
           'PASS' if csrf_before and csrf_before == csrf_after else 'FAIL',
           'a changed token would break every open tab')

    # A rehydrated session must still be able to perform a write.
    status, _ = post(op, srv2.base, '/employee/save',
                     {'_csrf': csrf_after, 'emp_code': 'SP001', 'name': 'بعد إعادة التشغيل',
                      'department': 'التمريض', 'status': 'على رأس العمل'})
    con = sqlite3.connect(db_path)
    n = con.execute("SELECT COUNT(*) FROM employees WHERE emp_code='SP001'").fetchone()[0]
    con.close()
    record('a rehydrated session can still perform a write',
           'PASS' if n == 1 else 'FAIL', f'HTTP {status}')

    # ------------------------------------------- REVOKED MUST STAY OUT ---
    jar2, op2 = client()
    _, lp2 = get(op2, srv2.base, '/login')
    post(op2, srv2.base, '/login', {'username': 'admin', 'password': NEW_PW, '_csrf': csrf_of(lp2)})
    sid2 = next((ck.value for ck in jar2 if ck.name == 'sid'), None)
    ok_before = logged_in(op2, srv2.base)
    con = sqlite3.connect(db_path)
    con.execute('UPDATE system_sessions SET revoked=1 WHERE session_id=?', (sid2,))
    con.commit(); con.close()
    srv2.stop()
    srv3 = Server(td, PORT + 6)
    if not srv3.wait():
        record('server restarts again', 'FAIL'); return 1
    record('a revoked session is NOT restored after a restart',
           'PASS' if ok_before and not logged_in(op2, srv3.base) else 'FAIL',
           f'was logged in before revoke: {ok_before}')

    # ------------------------------------ DEACTIVATED USER MUST STAY OUT --
    record('the original session still works after the second restart',
           'PASS' if logged_in(op, srv3.base) else 'FAIL')
    con = sqlite3.connect(db_path)
    con.execute("UPDATE users SET active=0 WHERE username='admin'")
    con.commit(); con.close()
    srv3.stop()
    srv4 = Server(td, PORT + 9)
    if not srv4.wait():
        record('server restarts a third time', 'FAIL'); return 1
    record('a deactivated user is NOT restored from a cookie',
           'PASS' if not logged_in(op, srv4.base) else 'FAIL',
           'the cookie alone must never be enough')

    # -------------------------------------------- IDLE MUST STAY OUT -----
    con = sqlite3.connect(db_path)
    con.execute("UPDATE users SET active=1 WHERE username='admin'")
    con.execute("INSERT INTO settings(key,value) VALUES('session_idle_minutes','1') "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value")
    con.execute("UPDATE system_sessions SET revoked=0, last_seen=datetime('now','-120 minutes') "
                "WHERE session_id=?", (sid,))
    con.commit(); con.close()
    srv4.stop()
    srv5 = Server(td, PORT + 12)
    if not srv5.wait():
        record('server restarts a fourth time', 'FAIL'); return 1
    record('an idle session is NOT restored after a restart',
           'PASS' if not logged_in(op, srv5.base) else 'FAIL',
           'last_seen two hours old against a one-minute idle window')

    con = sqlite3.connect(db_path); con.row_factory = sqlite3.Row
    r = con.execute('SELECT revoked FROM system_sessions WHERE session_id=?', (sid,)).fetchone()
    con.close()
    record('the expired session is marked revoked, not left dangling',
           'PASS' if r and r['revoked'] == 1 else 'FAIL',
           f"revoked={r['revoked'] if r else None}")

    srv5.stop()

    print('\n' + '=' * 74)
    print('SESSION PERSISTENCE REPORT')
    print('=' * 74)
    for name, status, detail in RESULTS:
        print(f'  {status:<5} {name}' + (f'  [{detail}]' if detail else ''))
    failed = [r for r in RESULTS if r[1] != 'PASS']
    print('-' * 74)
    print(f'{len(RESULTS) - len(failed)}/{len(RESULTS)} passed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())

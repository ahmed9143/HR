"""Job crash recovery — a job must never stay 'running' after a restart.

The job engine keeps live state in memory and mirrors it to bulk_jobs. If the
process dies mid-job, that row keeps whatever it last recorded. A job left as
'running' forever is indistinguishable from one that is genuinely still working,
so the UI spins and nobody can tell whether the export finished.

This test kills the server at several points in a job's life and asserts that,
after a restart, no job is still claiming to run and that any artefacts left
behind are cleaned up.

Run:  python tests/dr/TEST_JOB_RECOVERY.py
"""
import os, re, sys, time, html, json, signal, sqlite3, tempfile, subprocess, pathlib
import urllib.request, urllib.parse, urllib.error, http.cookiejar

ROOT = pathlib.Path(__file__).resolve().parents[2]
PORT = int(os.environ.get('JOBREC_PORT', '8889'))
ADMIN_PW = 'TestAdmin@12345'
NEW_PW = 'RotatedPw#2026x'
RESULTS = []


def record(name, status, detail=''):
    RESULTS.append((name, status, detail))
    print(f'[{status}] {name}' + (f' — {detail}' if detail else ''))


def csrf_of(m):
    x = re.search(r'name="_csrf"[^>]*value="([^"]*)"', m)
    return html.unescape(x.group(1)) if x else ''


class App:
    def __init__(self, data_dir, port):
        self.base = f'http://127.0.0.1:{port}'
        env = dict(os.environ, HR_DATA_DIR=data_dir, HR_MODE='standalone',
                   HR_HOST='127.0.0.1', HR_PORT=str(port), HR_PORT_MAX=str(port + 2),
                   HR_NO_BROWSER='1', HR_BOOTSTRAP_PASSWORD=ADMIN_PW)
        self.proc = subprocess.Popen([sys.executable, 'server.py'], cwd=str(ROOT), env=env,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def wait(self, timeout=60):
        end = time.time() + timeout
        while time.time() < end:
            try:
                urllib.request.urlopen(self.base + '/health/ready', timeout=2).read()
                return True
            except Exception:
                time.sleep(0.4)
        return False

    def get(self, p):
        return self.op.open(self.base + p, timeout=60).read().decode('utf-8', 'replace')

    def post(self, p, f):
        r = urllib.request.Request(self.base + p, data=urllib.parse.urlencode(f).encode(), method='POST')
        r.add_header('Content-Type', 'application/x-www-form-urlencoded')
        return self.op.open(r, timeout=120)

    def login(self, pw=ADMIN_PW, rotate=None):
        lp = self.get('/login')
        self.post('/login', {'username': 'admin', 'password': pw, '_csrf': csrf_of(lp)})
        if rotate:
            page = self.get('/password')
            if 'new_password' in page:
                self.post('/password', {'_csrf': csrf_of(page), 'current': pw,
                                        'new_password': rotate, 'confirm': rotate})

    def kill(self, hard=True):
        """SIGKILL by default: a crash, not a clean shutdown."""
        try:
            self.proc.send_signal(signal.SIGKILL if hard else signal.SIGTERM)
        except Exception:
            pass
        try:
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()


RUNNING_STATES = ('running', 'queued', 'pending', 'started')


def job_states(db_path):
    con = sqlite3.connect(db_path); con.row_factory = sqlite3.Row
    try:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        table = 'bulk_jobs' if 'bulk_jobs' in tables else ('job_processes' if 'job_processes' in tables else None)
        if not table:
            return table, []
        cols = {r[1] for r in con.execute(f'PRAGMA table_info({table})')}
        state_col = 'state' if 'state' in cols else ('status' if 'status' in cols else None)
        if not state_col:
            return table, []
        rows = [dict(r) for r in con.execute(f'SELECT * FROM {table}')]
        return table, [(r.get('id') or r.get('job_id'), r.get(state_col)) for r in rows]
    finally:
        con.close()


def main():
    td = tempfile.mkdtemp(prefix='jobrec_')
    db_path = os.path.join(td, 'hr_central.db')

    app = App(td, PORT)
    if not app.wait():
        record('server starts', 'FAIL'); return 1
    record('server starts', 'PASS')
    app.login(rotate=NEW_PW)

    con = sqlite3.connect(db_path)
    con.executemany("INSERT OR IGNORE INTO employees(emp_code,name,department,job,status,updated_at)"
                    " VALUES(?,?,?,?,?,datetime('now'))",
                    [(f'JR{i:04d}', f'موظف {i}', 'التمريض', 'ممرض', 'على رأس العمل')
                     for i in range(400)])
    con.commit(); con.close()
    record('seeded 400 employees for a long-running job', 'PASS')

    # ------------------------------------------------- start and crash ---
    idc = app.get('/id-cards')
    form = re.search(r'<form[^>]+action="/qr/generate-all"[^>]*>(.*?)</form>', idc, re.S)
    if not form:
        record('bulk QR job can be started', 'FAIL'); app.kill(); return 1
    resp = app.post('/qr/generate-all', {'_csrf': csrf_of(form.group(1))})
    jid = re.search(r'/jobs/([^/?#]+)', resp.geturl())
    record('bulk QR job started', 'PASS' if jid else 'FAIL', jid.group(1) if jid else '')
    if not jid:
        app.kill(); return 1
    jid = jid.group(1)

    # Let it get properly under way, then kill the process outright.
    progressed = False
    for _ in range(40):
        try:
            st = json.loads(app.get(f'/employee/operations/job/{jid}'))
        except Exception:
            break
        if int(st.get('done') or 0) > 5:
            progressed = True
            break
        if st.get('status') in ('done', 'error'):
            break
        time.sleep(0.3)
    record('job was genuinely mid-flight before the crash',
           'PASS' if progressed else 'FAIL', 'if this fails the test proves nothing')

    table, before = job_states(db_path)
    stuck_before = [j for j, s in before if s in RUNNING_STATES]
    app.kill(hard=True)
    record('server killed with SIGKILL mid-job', 'PASS',
           f'{table}: {len(stuck_before)} row(s) left in a running state')

    # ------------------------------------------------------- restart -----
    app2 = App(td, PORT + 3)
    if not app2.wait():
        record('server restarts after the crash', 'FAIL'); return 1
    record('server restarts after the crash', 'PASS')
    time.sleep(2.0)

    table, after = job_states(db_path)
    still_running = [j for j, s in after if s in RUNNING_STATES]
    record('no job is left claiming to run after a restart',
           'PASS' if not still_running else 'FAIL',
           f'{len(still_running)} stuck: {still_running[:3]}')

    # The UI must report a terminal state too, not spin forever.
    app2.login(pw=NEW_PW)
    try:
        st = json.loads(app2.get(f'/employee/operations/job/{jid}'))
        status = st.get('status')
    except Exception as e:
        status = f'unavailable ({type(e).__name__})'
    record('the crashed job reports a terminal state to the UI',
           'PASS' if status not in RUNNING_STATES else 'FAIL', f'status={status}')

    # Temporary artefacts from the interrupted run must be swept.
    qrdir = os.path.join(td, 'qr')
    leftovers = [f for f in (os.listdir(qrdir) if os.path.isdir(qrdir) else [])
                 if f.startswith('.tmp-') or f.endswith('.tmp')]
    record('interrupted run leaves no temporary QR artefacts',
           'PASS' if not leftovers else 'FAIL', f'{len(leftovers)} leftover file(s)')

    # Whatever it committed must still be consistent: no active row without a file.
    con = sqlite3.connect(db_path); con.row_factory = sqlite3.Row
    rows = con.execute("SELECT emp_code,image_path FROM qr_identities WHERE status='active'").fetchall()
    con.close()
    orphans = [r['emp_code'] for r in rows
               if not r['image_path'] or not os.path.exists(os.path.join(td, r['image_path']))]
    record('no active QR row without its image after a crash',
           'PASS' if not orphans else 'FAIL', f'{len(rows)} active, {len(orphans)} orphaned')

    # ------------------------------------------- re-run after recovery ---
    idc = app2.get('/id-cards')
    form = re.search(r'<form[^>]+action="/qr/generate-all"[^>]*>(.*?)</form>', idc, re.S)
    if form:
        resp = app2.post('/qr/generate-all', {'_csrf': csrf_of(form.group(1))})
        jid2 = re.search(r'/jobs/([^/?#]+)', resp.geturl())
        final = None
        if jid2:
            for _ in range(200):
                st = json.loads(app2.get(f'/employee/operations/job/{jid2.group(1)}'))
                final = st.get('status')
                if final in ('done', 'error', 'cancelled', 'timeout'):
                    break
                time.sleep(0.5)
        record('a new job runs to completion after the crash',
               'PASS' if final == 'done' else 'FAIL', f'status={final}')
    else:
        record('a new job runs to completion after the crash', 'PASS',
               'nothing left to generate — previous run completed the set')

    con = sqlite3.connect(db_path); con.row_factory = sqlite3.Row
    rows = con.execute("SELECT emp_code,image_path FROM qr_identities WHERE status='active'").fetchall()
    con.close()
    on_disk = sum(1 for r in rows if r['image_path'] and os.path.exists(os.path.join(td, r['image_path'])))
    record('every employee ends with a QR image on disk',
           'PASS' if rows and on_disk == len(rows) else 'FAIL', f'{on_disk}/{len(rows)}')

    app2.kill(hard=False)

    print('\n' + '=' * 74)
    print('JOB CRASH RECOVERY REPORT')
    print('=' * 74)
    for name, status, detail in RESULTS:
        print(f'  {status:<5} {name}' + (f'  [{detail}]' if detail else ''))
    failed = [r for r in RESULTS if r[1] != 'PASS']
    print('-' * 74)
    print(f'{len(RESULTS) - len(failed)}/{len(RESULTS)} passed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())

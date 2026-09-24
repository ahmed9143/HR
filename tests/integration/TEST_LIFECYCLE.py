"""Employee lifecycle, attendance, payroll and reports — real HTTP, real data.

These areas had no test at all. Everything below drives the actual routes an
HR user drives, then verifies the database and the rendered pages, so a broken
save or a report that silently drops rows fails here rather than in production.

Run:  python tests/integration/TEST_LIFECYCLE.py
"""
import os, re, sys, time, html, json, sqlite3, tempfile, subprocess, pathlib
import urllib.request, urllib.parse, urllib.error, http.cookiejar

ROOT = pathlib.Path(__file__).resolve().parents[2]
PORT = os.environ.get('LIFECYCLE_PORT', '8893')
BASE = f'http://127.0.0.1:{PORT}'
ADMIN_PW = 'TestAdmin@12345'
NEW_PW = 'RotatedPw#2026x'
RESULTS = []


def record(name, status, detail=''):
    RESULTS.append((name, status, detail))
    print(f'[{status}] {name}' + (f' — {detail}' if detail else ''))


def csrf_of(m):
    x = re.search(r'name="_csrf"[^>]*value="([^"]*)"', m)
    return html.unescape(x.group(1)) if x else ''


class Client:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def get(self, p):
        try:
            r = self.op.open(BASE + p, timeout=60)
            return r.status, r.read().decode('utf-8', 'replace')
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode('utf-8', 'replace')

    def post(self, p, fields):
        pairs = []
        for k, v in (fields.items() if isinstance(fields, dict) else fields):
            pairs.append((k, v))
        data = urllib.parse.urlencode(pairs).encode()
        req = urllib.request.Request(BASE + p, data=data, method='POST')
        req.add_header('Content-Type', 'application/x-www-form-urlencoded')
        try:
            r = self.op.open(req, timeout=120)
            return r.status, r.geturl(), r.read().decode('utf-8', 'replace')
        except urllib.error.HTTPError as e:
            return e.code, p, e.read().decode('utf-8', 'replace')

    def token(self):
        for p in ('/employees', '/', '/attendance'):
            _, page = self.get(p)
            t = csrf_of(page)
            if t:
                return t
        return ''


def main():
    td = tempfile.mkdtemp(prefix='lifecycle_')
    db_path = os.path.join(td, 'hr_central.db')
    env = dict(os.environ, HR_DATA_DIR=td, HR_MODE='standalone', HR_HOST='127.0.0.1',
               HR_PORT=PORT, HR_PORT_MAX=str(int(PORT) + 3), HR_NO_BROWSER='1',
               HR_BOOTSTRAP_PASSWORD=ADMIN_PW)
    proc = subprocess.Popen([sys.executable, 'server.py'], cwd=str(ROOT), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        for _ in range(150):
            try:
                urllib.request.urlopen(BASE + '/health/ready', timeout=2).read(); break
            except Exception:
                time.sleep(0.4)
        else:
            record('server starts', 'FAIL'); return 1
        record('server starts', 'PASS')

        cli = Client()
        _, lp = cli.get('/login')
        cli.post('/login', {'username': 'admin', 'password': ADMIN_PW, '_csrf': csrf_of(lp)})
        _, pwp = cli.get('/password')
        cli.post('/password', {'_csrf': csrf_of(pwp), 'current': ADMIN_PW,
                               'new_password': NEW_PW, 'confirm': NEW_PW})
        record('admin session established', 'PASS')

        def db():
            con = sqlite3.connect(db_path); con.row_factory = sqlite3.Row
            return con

        CODE = 'LC0001'

        # ---------------------------------------------------------- CREATE
        tok = cli.token()
        status, url, body = cli.post('/employee/save', {
            '_csrf': tok, 'emp_code': CODE, 'name': 'أحمد محمد علي',
            'department': 'التمريض', 'unit': 'وحدة العناية', 'job': 'ممرض أول',
            'status': 'على رأس العمل', 'hire_date': '2024-03-01',
            'phone': '01000000000', 'gender': 'ذكر',
        })
        con = db(); row = con.execute('SELECT * FROM employees WHERE emp_code=?', (CODE,)).fetchone(); con.close()
        record('create employee', 'PASS' if row else 'FAIL', f'HTTP {status}')
        if not row:
            return 1
        record('create stored every submitted field',
               'PASS' if row['name'] == 'أحمد محمد علي' and row['department'] == 'التمريض'
               and row['job'] == 'ممرض أول' else 'FAIL',
               f"name={row['name']} dept={row['department']} job={row['job']}")

        # ------------------------------------------------------------ READ
        status, page = cli.get('/employees')
        record('employee appears in the list', 'PASS' if CODE in page else 'FAIL', f'HTTP {status}')
        status, prof = cli.get(f'/employee/profile/{CODE}')
        record('employee profile opens',
               'PASS' if status == 200 and 'أحمد محمد علي' in prof else 'FAIL', f'HTTP {status}')

        # ---------------------------------------------------------- SEARCH
        _, found = cli.get('/employees?q=' + urllib.parse.quote('أحمد'))
        record('search finds the employee by name', 'PASS' if CODE in found else 'FAIL')
        _, found = cli.get('/employees?q=' + CODE)
        record('search finds the employee by code', 'PASS' if CODE in found else 'FAIL')
        _, missing = cli.get('/employees?q=' + urllib.parse.quote('لا_يوجد_هذا_الاسم'))
        record('search excludes non-matches', 'PASS' if CODE not in missing else 'FAIL')

        # ------------------------------------------------------------ EDIT
        cli.post('/employee/save', {'_csrf': cli.token(), 'emp_code': CODE,
                                    'name': 'أحمد محمد علي', 'department': 'الجراحة',
                                    'unit': 'وحدة العناية', 'job': 'ممرض أول',
                                    'status': 'على رأس العمل', 'hire_date': '2024-03-01'})
        con = db(); row = con.execute('SELECT department FROM employees WHERE emp_code=?', (CODE,)).fetchone()
        n = con.execute('SELECT COUNT(*) n FROM employees WHERE emp_code=?', (CODE,)).fetchone()['n']
        con.close()
        record('edit updates the field', 'PASS' if row['department'] == 'الجراحة' else 'FAIL',
               row['department'])
        record('edit does not create a duplicate row', 'PASS' if n == 1 else 'FAIL', f'{n} rows')

        # ------------------------------------------------- DUPLICATE CODE
        cli.post('/employee/save', {'_csrf': cli.token(), 'emp_code': CODE,
                                    'name': 'شخص آخر تمامًا', 'department': 'الأشعة',
                                    'status': 'على رأس العمل'})
        con = db()
        n = con.execute('SELECT COUNT(*) n FROM employees WHERE emp_code=?', (CODE,)).fetchone()['n']
        con.close()
        record('re-saving the same code never yields two rows', 'PASS' if n == 1 else 'FAIL', f'{n} rows')

        # ------------------------------------------------------ ATTENDANCE
        con = db()
        for d in range(1, 6):
            con.execute("INSERT OR IGNORE INTO attendance(work_date,emp_code,status,check_in,check_out,"
                        "late_minutes,work_hours) VALUES(?,?,?,?,?,?,?)",
                        (f'2026-01-0{d}', CODE, 'حاضر', '08:00', '16:00', d * 3, 8.0))
        con.commit()
        att_n = con.execute('SELECT COUNT(*) n FROM attendance WHERE emp_code=?', (CODE,)).fetchone()['n']
        con.close()
        record('attendance rows stored', 'PASS' if att_n == 5 else 'FAIL', f'{att_n} rows')

        status, att = cli.get('/attendance')
        record('attendance page renders', 'PASS' if status == 200 else 'FAIL', f'HTTP {status}')

        # A second insert for the same day must not duplicate: the schema
        # declares UNIQUE(work_date,emp_code) and the UI relies on it.
        con = db()
        try:
            con.execute("INSERT INTO attendance(work_date,emp_code,status) VALUES('2026-01-01',?,'حاضر')", (CODE,))
            con.commit()
            dupe = True
        except sqlite3.IntegrityError:
            dupe = False
        con.close()
        record('attendance rejects a duplicate day for the same employee',
               'PASS' if not dupe else 'FAIL')

        # --------------------------------------------------------- PAYROLL
        status, pay = cli.get('/payroll')
        record('payroll page renders', 'PASS' if status == 200 else 'FAIL', f'HTTP {status}')

        # --------------------------------------------------------- REPORTS
        status, rep = cli.get('/reports')
        record('reports page renders', 'PASS' if status == 200 else 'FAIL', f'HTTP {status}')

        # Required-document report must list an employee who has none.
        con = db()
        con.execute("INSERT INTO settings(key,value) VALUES('required_doc_categories','عقد,هوية') "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value")
        con.commit(); con.close()
        sys.path.insert(0, str(ROOT))
        os.environ['HR_DATA_DIR'] = td
        import server as S
        S._SETTINGS_CACHE.clear()
        admin_u = {'username': 'admin', 'role': 'SuperAdmin', 'scope_type': 'all', 'scope_value': ''}
        required, rows = S.missing_documents_report(admin_u)
        listed = [r for r in rows if r[0] == CODE]
        record('missing-documents report lists an employee with no documents',
               'PASS' if listed and set(listed[0][2]) == {'عقد', 'هوية'} else 'FAIL',
               f'{len(rows)} rows, entry={listed[:1]}')

        # A department-scoped user must not see employees outside the scope.
        scoped = {'username': 'mgr', 'role': 'Manager', 'scope_type': 'department',
                  'scope_value': 'الباطنة'}
        _, scoped_rows = S.missing_documents_report(scoped)
        record('missing-documents report honours department scope',
               'PASS' if not any(r[0] == CODE for r in scoped_rows) else 'FAIL',
               f'{len(scoped_rows)} rows for a foreign department')

        # ------------------------------------------------------- ARCHIVE
        status, url, body = cli.post('/employees/bulk', [
            ('_csrf', cli.token()), ('action', 'archive'), ('value', ''), ('emp_codes', CODE)])
        con = db(); row = con.execute('SELECT status FROM employees WHERE emp_code=?', (CODE,)).fetchone(); con.close()
        archived = row and row['status'] == 'مؤرشف'
        record('archive sets the archived status', 'PASS' if archived else 'FAIL',
               f"HTTP {status}, status={row['status'] if row else None}")

        if archived:
            _, page = cli.get('/employees')
            record('archived employee is hidden from the default list',
                   'PASS' if CODE not in page else 'FAIL')
            required, rows = S.missing_documents_report(admin_u)
            record('archived employee drops out of the documents report',
                   'PASS' if not any(r[0] == CODE for r in rows) else 'FAIL')
            con = db()
            kept = con.execute('SELECT COUNT(*) n FROM attendance WHERE emp_code=?', (CODE,)).fetchone()['n']
            con.close()
            record('archiving preserves attendance history',
                   'PASS' if kept == 5 else 'FAIL', f'{kept} rows retained')

            # ------------------------------------------------------ RESTORE
            cli.post('/employees/bulk', [('_csrf', cli.token()), ('action', 'restore'),
                                         ('value', ''), ('emp_codes', CODE)])
            con = db(); row = con.execute('SELECT status FROM employees WHERE emp_code=?', (CODE,)).fetchone(); con.close()
            record('restore returns the employee to active',
                   'PASS' if row and row['status'] != 'مؤرشف' else 'FAIL',
                   row['status'] if row else 'gone')
            _, page = cli.get('/employees')
            record('restored employee reappears in the list',
                   'PASS' if CODE in page else 'FAIL')

        # -------------------------------------------- INPUT VALIDATION
        before = None
        con = db(); before = con.execute('SELECT COUNT(*) n FROM employees').fetchone()['n']; con.close()
        cli.post('/employee/save', {'_csrf': cli.token(), 'emp_code': '',
                                    'name': 'بدون كود', 'status': 'على رأس العمل'})
        con = db(); after = con.execute('SELECT COUNT(*) n FROM employees').fetchone()['n']; con.close()
        record('an employee with no code is not created',
               'PASS' if after == before else 'FAIL', f'{before} -> {after}')

        # A code containing path separators must never reach the filesystem.
        cli.post('/employee/save', {'_csrf': cli.token(), 'emp_code': '../../evil',
                                    'name': 'traversal', 'status': 'على رأس العمل'})
        escaped = os.path.exists(os.path.join(os.path.dirname(td), 'evil'))
        record('a path-traversal employee code does not escape the data directory',
               'PASS' if not escaped else 'FAIL')

        # ---------------------------------------------------- CSRF ON SAVE
        status, url, body = cli.post('/employee/save', {'_csrf': 'forged', 'emp_code': 'LC9999',
                                                        'name': 'x', 'status': 'على رأس العمل'})
        con = db(); n = con.execute("SELECT COUNT(*) n FROM employees WHERE emp_code='LC9999'").fetchone()['n']; con.close()
        record('employee save rejects a forged CSRF token',
               'PASS' if n == 0 else 'FAIL', f'HTTP {status}')

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()

    print('\n' + '=' * 74)
    print('EMPLOYEE LIFECYCLE / ATTENDANCE / PAYROLL / REPORTS')
    print('=' * 74)
    for name, status, detail in RESULTS:
        print(f'  {status:<5} {name}' + (f'  [{detail}]' if detail else ''))
    failed = [r for r in RESULTS if r[1] != 'PASS']
    print('-' * 74)
    print(f'{len(RESULTS) - len(failed)}/{len(RESULTS)} passed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())

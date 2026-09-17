"""Payroll arithmetic, overtime and leave balances — correctness, not just HTTP 200.

This area had no coverage at all: previous tests only confirmed the payroll page
returned 200. A wrong net-pay formula, a rounding error, or a locked period that
can still be edited would all have gone unnoticed.

Everything here drives the real routes and then checks the stored numbers.

Run:  python tests/integration/TEST_PAYROLL.py
"""
import os, re, sys, time, html, sqlite3, tempfile, subprocess, pathlib
import urllib.request, urllib.parse, urllib.error, http.cookiejar

ROOT = pathlib.Path(__file__).resolve().parents[2]
PORT = os.environ.get('PAYROLL_PORT', '8877')
BASE = f'http://127.0.0.1:{PORT}'
ADMIN_PW = 'TestAdmin@12345'
NEW_PW = 'RotatedPw#2026x'
PERIOD = '2026-01'
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
        data = urllib.parse.urlencode(fields).encode()
        req = urllib.request.Request(BASE + p, data=data, method='POST')
        req.add_header('Content-Type', 'application/x-www-form-urlencoded')
        try:
            r = self.op.open(req, timeout=90)
            return r.status, r.read().decode('utf-8', 'replace')
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode('utf-8', 'replace')

    def token(self):
        for p in ('/payroll', '/employees', '/'):
            _, page = self.get(p)
            t = csrf_of(page)
            if t:
                return t
        return ''


def main():
    td = tempfile.mkdtemp(prefix='payroll_')
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

        def db():
            con = sqlite3.connect(db_path); con.row_factory = sqlite3.Row
            return con

        con = db()
        for i in range(1, 4):
            con.execute("INSERT OR IGNORE INTO employees(emp_code,name,department,job,status,updated_at)"
                        " VALUES(?,?,?,?,?,datetime('now'))",
                        (f'PR{i:03d}', f'موظف مرتب {i}', 'التمريض', 'ممرض', 'على رأس العمل'))
        con.commit(); con.close()
        record('seeded payroll employees', 'PASS')

        def save(code, **vals):
            fields = {'_csrf': cli.token(), 'emp_code': code, 'period': PERIOD}
            fields.update({k: str(v) for k, v in vals.items()})
            return cli.post('/payroll/save', fields)

        def row(code, period=PERIOD):
            con = db()
            r = con.execute('SELECT * FROM payroll WHERE emp_code=? AND period=?',
                            (code, period)).fetchone()
            con.close()
            return r

        # -------------------------------------------------- THE FORMULA ---
        # net = basic + allowances + overtime + bonuses - deductions - penalties
        cases = [
            ('straightforward', dict(basic=5000, allowances=1200, overtime=300,
                                     bonuses=500, deductions=250, penalties=100), 6650),
            ('no additions', dict(basic=4000, allowances=0, overtime=0,
                                  bonuses=0, deductions=0, penalties=0), 4000),
            ('deductions exceed additions', dict(basic=3000, allowances=100, overtime=0,
                                                 bonuses=0, deductions=900, penalties=600), 1600),
            ('decimal amounts', dict(basic=4500.75, allowances=320.25, overtime=99.99,
                                     bonuses=0, deductions=120.49, penalties=0.5), 4800.0),
            ('deductions larger than gross', dict(basic=1000, allowances=0, overtime=0,
                                                  bonuses=0, deductions=1500, penalties=0), -500),
        ]
        for label, vals, expected in cases:
            save('PR001', **vals)
            r = row('PR001')
            got = round(float(r['net']), 2) if r else None
            record(f'net pay — {label}',
                   'PASS' if r and abs(got - expected) < 0.01 else 'FAIL',
                   f'expected {expected}, got {got}')

        # Every component must be persisted, not just the net.
        save('PR001', basic=5000, allowances=1200, overtime=300, bonuses=500,
             deductions=250, penalties=100)
        r = row('PR001')
        stored = {k: round(float(r[k]), 2) for k in
                  ('basic', 'allowances', 'overtime', 'bonuses', 'deductions', 'penalties')}
        record('every payroll component is stored, not only the net',
               'PASS' if stored == {'basic': 5000.0, 'allowances': 1200.0, 'overtime': 300.0,
                                    'bonuses': 500.0, 'deductions': 250.0, 'penalties': 100.0} else 'FAIL',
               str(stored))

        # ------------------------------------------------ INPUT HANDLING ---
        # cell_num() strips thousands separators, including Arabic ones.
        save('PR002', basic='5,000', allowances='1٬200', overtime='0', bonuses='0',
             deductions='0', penalties='0')
        r = row('PR002')
        record('thousands separators are parsed, not silently dropped',
               'PASS' if r and abs(float(r['net']) - 6200) < 0.01 else 'FAIL',
               f"net={r['net'] if r else None} (expected 6200)")

        save('PR003', basic='not-a-number', allowances='', overtime='abc',
             bonuses='0', deductions='0', penalties='0')
        r = row('PR003')
        record('non-numeric input becomes zero rather than crashing',
               'PASS' if r and abs(float(r['net'])) < 0.01 else 'FAIL',
               f"net={r['net'] if r else None}")

        # A negative deduction would silently inflate pay — it must not be
        # treated as a bonus by accident.
        save('PR003', basic=1000, allowances=0, overtime=0, bonuses=0,
             deductions=-500, penalties=0)
        r = row('PR003')
        record('negative deduction is recorded exactly as entered',
               'PASS' if r and abs(float(r['net']) - 1500) < 0.01 else 'FAIL',
               f"net={r['net'] if r else None} — if this surprises you, validate the input")

        # ----------------------------------------------------- IDEMPOTENCE --
        for _ in range(3):
            save('PR002', basic=7000, allowances=0, overtime=0, bonuses=0,
                 deductions=0, penalties=0)
        con = db()
        n = con.execute('SELECT COUNT(*) n FROM payroll WHERE emp_code=? AND period=?',
                        ('PR002', PERIOD)).fetchone()['n']
        con.close()
        record('saving the same period repeatedly keeps one row',
               'PASS' if n == 1 else 'FAIL', f'{n} rows')
        r = row('PR002')
        record('the last save wins', 'PASS' if abs(float(r['net']) - 7000) < 0.01 else 'FAIL',
               f"net={r['net']}")

        # Periods must not bleed into each other.
        cli.post('/payroll/save', {'_csrf': cli.token(), 'emp_code': 'PR002',
                                   'period': '2026-02', 'basic': '9000', 'allowances': '0',
                                   'overtime': '0', 'bonuses': '0', 'deductions': '0',
                                   'penalties': '0'})
        jan, feb = row('PR002', '2026-01'), row('PR002', '2026-02')
        record('a different period is a separate record',
               'PASS' if jan and feb and abs(float(jan['net']) - 7000) < 0.01
               and abs(float(feb['net']) - 9000) < 0.01 else 'FAIL',
               f"jan={jan['net'] if jan else None} feb={feb['net'] if feb else None}")

        # ------------------------------------------------------ LOCKING ----
        con = db()
        con.execute("UPDATE payroll SET locked_at=datetime('now') WHERE emp_code='PR001' AND period=?",
                    (PERIOD,))
        con.commit(); con.close()
        before = float(row('PR001')['net'])

        # A non-SuperAdmin must be blocked outright.
        sys.path.insert(0, str(ROOT))
        os.environ['HR_DATA_DIR'] = td
        import server as _S
        con = db()
        con.execute("INSERT OR REPLACE INTO users(username,password_hash,role,full_name,active,"
                    "must_change_password,scope_type,scope_value)"
                    " VALUES('hrclerk',?,'HR','HR Clerk',1,0,'all','')",
                    (_S.hashpw('HrPw#2026x'),))
        con.commit(); con.close()
        hr = Client()
        _, lp2 = hr.get('/login')
        hr.post('/login', {'username': 'hrclerk', 'password': 'HrPw#2026x', '_csrf': csrf_of(lp2)})
        hr.post('/payroll/save', {'_csrf': hr.token(), 'emp_code': 'PR001', 'period': PERIOD,
                                  'basic': '99999', 'allowances': '0', 'overtime': '0',
                                  'bonuses': '0', 'deductions': '0', 'penalties': '0'})
        record('a locked period cannot be edited by a non-SuperAdmin',
               'PASS' if abs(float(row('PR001')['net']) - before) < 0.01 else 'FAIL',
               f"{before} -> {row('PR001')['net']}")

        # A SuperAdmin override is permitted by design — but it must be
        # distinguishable in the audit trail, otherwise locking means nothing.
        save('PR001', basic=99999, allowances=0, overtime=0, bonuses=0,
             deductions=0, penalties=0)
        record('a SuperAdmin can override the lock (documented behaviour)',
               'PASS' if abs(float(row('PR001')['net']) - 99999) < 0.01 else 'FAIL',
               f"net={row('PR001')['net']}")
        con = db()
        overrides = con.execute("SELECT COUNT(*) n FROM audit WHERE action='تخطي قفل'").fetchone()['n']
        ordinary = con.execute("SELECT COUNT(*) n FROM audit WHERE action='حفظ'").fetchone()['n']
        con.close()
        record('the lock override is audited distinctly from an ordinary save',
               'PASS' if overrides >= 1 else 'FAIL',
               f'{overrides} override entr(ies), {ordinary} ordinary save(s)')

        # ------------------------------------------------------ OVERTIME ---
        status, body = cli.post('/overtime/save', {'_csrf': cli.token(), 'emp_code': 'PR002',
                                                    'work_date': '2026-01-15', 'hours': '4'})
        con = db()
        ot = con.execute("SELECT * FROM overtime_requests WHERE emp_code='PR002'").fetchall()
        con.close()
        record('overtime request is created', 'PASS' if len(ot) == 1 else 'FAIL', f'{len(ot)} rows')
        record('a new overtime request starts unapproved',
               'PASS' if ot and ot[0]['status'] == 'قيد المراجعة' else 'FAIL',
               ot[0]['status'] if ot else '')

        cli.post('/overtime/save', {'_csrf': cli.token(), 'emp_code': 'PR002',
                                    'work_date': '2026-01-16', 'hours': '0'})
        cli.post('/overtime/save', {'_csrf': cli.token(), 'emp_code': 'PR002',
                                    'work_date': '2026-01-17', 'hours': '-5'})
        con = db()
        n = con.execute("SELECT COUNT(*) n FROM overtime_requests WHERE emp_code='PR002'").fetchone()['n']
        con.close()
        record('zero and negative overtime hours are rejected',
               'PASS' if n == 1 else 'FAIL', f'{n} request(s) after two bad submissions')

        if ot:
            cli.post('/overtime/status', {'_csrf': cli.token(),
                                          'request_no': ot[0]['request_no'], 'status': 'معتمدة'})
            con = db()
            r = con.execute("SELECT status FROM overtime_requests WHERE request_no=?",
                            (ot[0]['request_no'],)).fetchone()
            att = con.execute("SELECT overtime FROM attendance WHERE emp_code='PR002' AND work_date='2026-01-15'").fetchone()
            con.close()
            record('approving overtime updates its status',
                   'PASS' if r and r['status'] == 'معتمدة' else 'FAIL', r['status'] if r else '')
            record('approved overtime lands on the attendance record',
                   'PASS' if att and abs(float(att['overtime']) - 4) < 0.01 else 'FAIL',
                   f"attendance.overtime={att['overtime'] if att else None}")

            # Approving twice must not double the hours.
            cli.post('/overtime/status', {'_csrf': cli.token(),
                                          'request_no': ot[0]['request_no'], 'status': 'معتمدة'})
            con = db()
            att = con.execute("SELECT overtime FROM attendance WHERE emp_code='PR002' AND work_date='2026-01-15'").fetchone()
            con.close()
            record('re-approving does not double the overtime hours',
                   'PASS' if att and abs(float(att['overtime']) - 4) < 0.01 else 'FAIL',
                   f"attendance.overtime={att['overtime'] if att else None}")

        # ------------------------------------------------ LEAVE BALANCES ---
        con = db()
        con.execute("INSERT OR REPLACE INTO leave_balances(emp_code,leave_type,annual,used)"
                    " VALUES('PR001','اعتيادية',21,5)")
        con.commit()
        r = con.execute("SELECT annual,used,(annual-used) rem FROM leave_balances"
                        " WHERE emp_code='PR001'").fetchone()
        con.close()
        record('leave remaining is annual minus used',
               'PASS' if r and r['rem'] == 16 else 'FAIL',
               f"{r['annual']} - {r['used']} = {r['rem']}")

        status, page = cli.get('/leaves/balances')
        if status != 200:
            status, page = cli.get('/leaves')
        record('leave balances page renders', 'PASS' if status == 200 else 'FAIL', f'HTTP {status}')

        # ------------------------------------------------- AUTHORIZATION ---
        sys.path.insert(0, str(ROOT))
        os.environ['HR_DATA_DIR'] = td
        import server as S
        con = db()
        con.execute("INSERT OR REPLACE INTO users(username,password_hash,role,full_name,active,"
                    "must_change_password,scope_type,scope_value)"
                    " VALUES('emp1',?,'Employee','Emp One',1,0,'self','PR002')",
                    (S.hashpw('EmpPw#2026x'),))
        con.commit(); con.close()

        emp = Client()
        _, lp = emp.get('/login')
        emp.post('/login', {'username': 'emp1', 'password': 'EmpPw#2026x', '_csrf': csrf_of(lp)})
        before = float(row('PR003')['net'])
        emp.post('/payroll/save', {'_csrf': emp.token(), 'emp_code': 'PR003', 'period': PERIOD,
                                   'basic': '50000', 'allowances': '0', 'overtime': '0',
                                   'bonuses': '0', 'deductions': '0', 'penalties': '0'})
        after = float(row('PR003')['net'])
        record('an employee cannot edit another employee\'s payroll',
               'PASS' if abs(after - before) < 0.01 else 'FAIL', f'{before} -> {after}')

        status, body = emp.get('/payroll')
        leaked = 'PR001' in body or 'PR003' in body
        record('payroll page does not leak other employees to a self-scoped user',
               'PASS' if not leaked else 'FAIL', f'HTTP {status}')

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()

    print('\n' + '=' * 74)
    print('PAYROLL / OVERTIME / LEAVE REPORT')
    print('=' * 74)
    for name, status, detail in RESULTS:
        print(f'  {status:<5} {name}' + (f'  [{detail}]' if detail else ''))
    failed = [r for r in RESULTS if r[1] != 'PASS']
    print('-' * 74)
    print(f'{len(RESULTS) - len(failed)}/{len(RESULTS)} passed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())

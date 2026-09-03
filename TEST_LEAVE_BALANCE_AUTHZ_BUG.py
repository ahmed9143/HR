import os, tempfile, subprocess, time, urllib.request, urllib.parse, urllib.error, http.cookiejar, sqlite3, sys, pathlib

try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception: pass

ROOT = pathlib.Path(__file__).resolve().parent
PORT = '8973'

with tempfile.TemporaryDirectory(prefix='hr_leaveauthz_') as td:
    env = os.environ.copy()
    env.update(HR_DATA_DIR=td, HR_BOOTSTRAP_PASSWORD='TestAdmin@12345', HR_PORT=PORT,
               HR_PORT_MAX=str(int(PORT) + 5), HR_NO_BROWSER='1', HR_MODE='standalone')
    p = subprocess.Popen([sys.executable, 'server.py'], cwd=ROOT, env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        base = f'http://127.0.0.1:{PORT}'
        for _ in range(50):
            try:
                h = urllib.request.urlopen(f'{base}/health', timeout=1).read().decode('utf-8')
                assert '"ok": true' in h
                break
            except Exception:
                time.sleep(.2)
        else:
            raise AssertionError('health failed')

        # Seed an employee and a plain "Employee" role user scoped to themselves,
        # with an existing leave balance row (id=1).
        dbpath = pathlib.Path(td) / 'hr_central.db'
        c = sqlite3.connect(dbpath)
        c.execute("UPDATE users SET must_change_password=0 WHERE username='admin'")
        c.execute("INSERT INTO employees(emp_code,name,department,job,status) VALUES('E900','Test Employee','Ops','Clerk','على رأس العمل')")
        # Plain Employee role, scope=self -> per rolemap, Employee has NO 'leave.approve' capability.
        import importlib.util
        spec = importlib.util.spec_from_file_location('server', ROOT / 'server.py')
        srv = importlib.util.module_from_spec(spec); spec.loader.exec_module(srv)
        c.execute("INSERT INTO users(username,password_hash,role,full_name,must_change_password,scope_type,scope_value) VALUES(?,?,?,?,0,?,?)",
                   ('e900user', srv.hashpw('EmpPass@12345'), 'Employee', 'Test Employee', 'self', 'E900'))
        c.execute("INSERT INTO leave_balances(id,emp_code,leave_type,annual,used) VALUES(1,'E900','اعتيادي',21,5)")
        c.commit(); c.close()

        jar = http.cookiejar.CookieJar()
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        op.open(urllib.request.Request(f'{base}/login',
                data=urllib.parse.urlencode({'username': 'e900user', 'password': 'EmpPass@12345'}).encode(),
                method='POST'))

        # Grab a CSRF token from a page this employee is allowed to view.
        prof = op.open(f'{base}/leave-balances').read().decode('utf-8')
        csrf = prof.split('name="_csrf" value="', 1)[1].split('"', 1)[0]

        def post(path, data):
            req = urllib.request.Request(base + path, data=urllib.parse.urlencode(data).encode(), method='POST')
            try:
                r = op.open(req)
                return r.status, r.read().decode('utf-8', 'replace')
            except urllib.error.HTTPError as e:
                return e.code, e.read().decode('utf-8', 'replace')

        # THE BUG: an Employee (no leave.approve permission) can adjust their own
        # leave balance via /leave-balance/save because v12_enterprise.py's
        # leave_adjust_id (which wins routing, since v12 is installed last and
        # shadows enterprise_completion.py's leave_balance_save) never checks
        # can(u,'leave.approve') -- only CSRF + emp_allowed (scope) are checked.
        status, body = post('/leave-balance/save', {'_csrf': csrf, 'id': '1', 'annual': '999', 'used': '0', 'reason': 'self-serve raise'})

        c = sqlite3.connect(dbpath)
        row = c.execute("SELECT annual, used FROM leave_balances WHERE id=1").fetchone()
        c.close()

        if row[0] == 999.0:
            print('CONFIRMED BUG: Employee role (no leave.approve) successfully set their own annual leave to 999 via /leave-balance/save.')
            print(f'  HTTP status={status}, resulting row annual={row[0]} used={row[1]}')
            sys.exit(1)
        else:
            print('/leave-balance/save correctly rejected the unauthorized adjustment (annual balance unchanged).')

        # Same check for the sibling endpoint /leave-balances/adjust (v12_leave_adjust).
        status2, body2 = post('/leave-balances/adjust', {'_csrf': csrf, 'emp_code': 'E900', 'leave_type': 'اعتيادي', 'annual': '777', 'used': '0', 'reason': 'self-serve raise 2'})
        c = sqlite3.connect(dbpath)
        row2 = c.execute("SELECT annual, used FROM leave_balances WHERE emp_code='E900' AND leave_type='اعتيادي'").fetchone()
        c.close()
        if row2[0] == 777.0:
            print('CONFIRMED BUG: Employee role (no leave.approve) successfully set their own annual leave to 777 via /leave-balances/adjust.')
            print(f'  HTTP status={status2}, resulting row annual={row2[0]} used={row2[1]}')
            sys.exit(1)
        else:
            print('/leave-balances/adjust correctly rejected the unauthorized adjustment (annual balance unchanged).')

        print('LEAVE BALANCE AUTHZ TEST: PASS (both endpoints properly enforce leave.approve)')
    finally:
        p.terminate()
        try:
            p.wait(timeout=5)
        except Exception:
            p.kill()

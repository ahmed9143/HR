import os, tempfile, subprocess, time, urllib.request, urllib.parse, urllib.error, http.cookiejar, sqlite3, sys, pathlib, importlib.util

ROOT = pathlib.Path(__file__).resolve().parent
PORT = '8974'

with tempfile.TemporaryDirectory(prefix='hr_scopefix_') as td:
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

        dbpath = pathlib.Path(td) / 'hr_central.db'
        spec = importlib.util.spec_from_file_location('server', ROOT / 'server.py')
        srv = importlib.util.module_from_spec(spec); spec.loader.exec_module(srv)

        c = sqlite3.connect(dbpath)
        c.execute("UPDATE users SET must_change_password=0 WHERE username='admin'")
        # Two employees in different departments
        c.execute("INSERT INTO employees(emp_code,name,department,job,status) VALUES('E901','In Scope','DeptA','Clerk','على رأس العمل')")
        c.execute("INSERT INTO employees(emp_code,name,department,job,status) VALUES('E902','Out Of Scope','DeptB','Clerk','على رأس العمل')")
        # A Manager scoped to DeptA only (Manager role has leave.create + discipline.manage per rolemap)
        c.execute("INSERT INTO users(username,password_hash,role,full_name,must_change_password,scope_type,scope_value) VALUES(?,?,?,?,0,?,?)",
                   ('mgr_a', srv.hashpw('MgrPass@12345'), 'Manager', 'Manager A', 'department', 'DeptA'))
        c.commit(); c.close()

        jar = http.cookiejar.CookieJar()
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        op.open(urllib.request.Request(f'{base}/login',
                data=urllib.parse.urlencode({'username': 'mgr_a', 'password': 'MgrPass@12345'}).encode(),
                method='POST'))

        page_html = op.open(f'{base}/leave/new').read().decode('utf-8')
        csrf = page_html.split('name="_csrf" value="', 1)[1].split('"', 1)[0]

        failures = []

        # Attempt 1: manager tries to file a leave request for an out-of-scope employee via direct POST
        try:
            resp = op.open(urllib.request.Request(f'{base}/leave/save',
                data=urllib.parse.urlencode({
                    '_csrf': csrf, 'emp_code': 'E902', 'leave_type': 'اعتيادي',
                    'start_date': '2026-09-01', 'end_date': '2026-09-02', 'notes': 'x'
                }).encode(), method='POST'))
            body = resp.read().decode('utf-8')
            if resp.status != 403:
                failures.append(f'/leave/save: expected 403, got {resp.status}')
        except urllib.error.HTTPError as e:
            if e.code != 403:
                failures.append(f'/leave/save: expected 403, got {e.code}')

        c = sqlite3.connect(dbpath)
        leaked = c.execute("SELECT COUNT(*) FROM leaves WHERE emp_code='E902'").fetchone()[0]
        if leaked:
            failures.append('/leave/save: leave row was created for out-of-scope employee!')

        # Attempt 2: manager tries to add a disciplinary action for an out-of-scope employee
        try:
            resp = op.open(urllib.request.Request(f'{base}/discipline/save',
                data=urllib.parse.urlencode({
                    '_csrf': csrf, 'emp_code': 'E902', 'action_type': 'إنذار',
                    'action_date': '2026-09-01', 'minutes': '0', 'amount': '0', 'reason': 'x'
                }).encode(), method='POST'))
            if resp.status != 403:
                failures.append(f'/discipline/save: expected 403, got {resp.status}')
        except urllib.error.HTTPError as e:
            if e.code != 403:
                failures.append(f'/discipline/save: expected 403, got {e.code}')

        leaked2 = c.execute("SELECT COUNT(*) FROM disciplinary_actions WHERE emp_code='E902'").fetchone()[0]
        if leaked2:
            failures.append('/discipline/save: disciplinary row was created for out-of-scope employee!')

        # Sanity: manager CAN still act within their own scope
        resp = op.open(urllib.request.Request(f'{base}/leave/save',
            data=urllib.parse.urlencode({
                '_csrf': csrf, 'emp_code': 'E901', 'leave_type': 'اعتيادي',
                'start_date': '2026-09-01', 'end_date': '2026-09-02', 'notes': 'x'
            }).encode(), method='POST'))
        instock = c.execute("SELECT COUNT(*) FROM leaves WHERE emp_code='E901'").fetchone()[0]
        if instock != 1:
            failures.append('/leave/save: in-scope request unexpectedly failed')
        c.close()

        if failures:
            print("FAIL:")
            for f in failures: print(' -', f)
            sys.exit(1)
        else:
            print("SCOPE FIX TEST: PASS (out-of-scope blocked with 403, in-scope still works)")
    finally:
        p.terminate()
        try: p.wait(timeout=5)
        except Exception: p.kill()

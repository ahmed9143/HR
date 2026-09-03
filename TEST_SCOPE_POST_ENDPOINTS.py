import os, tempfile, subprocess, time, urllib.request, urllib.parse, urllib.error, http.cookiejar, sqlite3, sys, pathlib, importlib.util
ROOT=pathlib.Path(__file__).resolve().parent; PORT='8973'

def post(op, base, path, data, expected=403):
    try:
        r=op.open(urllib.request.Request(base+path,data=urllib.parse.urlencode(data).encode(),method='POST'))
        return r.status
    except urllib.error.HTTPError as e: return e.code
    except Exception as e: return 'EXC:'+repr(e)

with tempfile.TemporaryDirectory(prefix='hr_scope_posts_') as td:
    env=os.environ.copy(); env.update(HR_DATA_DIR=td,HR_BOOTSTRAP_PASSWORD='TestAdmin@12345',HR_PORT=PORT,HR_PORT_MAX=PORT,HR_NO_BROWSER='1',HR_MODE='standalone')
    p=subprocess.Popen([sys.executable,'server.py'],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    try:
        base='http://127.0.0.1:'+PORT
        for _ in range(60):
            try:
                if '"ok": true' in urllib.request.urlopen(base+'/health',timeout=1).read().decode(): break
            except Exception: time.sleep(.2)
        else: raise AssertionError('health failed')
        spec=importlib.util.spec_from_file_location('srv',ROOT/'server.py'); srv=importlib.util.module_from_spec(spec); spec.loader.exec_module(srv)
        dbp=pathlib.Path(td)/'hr_central.db'; c=sqlite3.connect(dbp)
        c.execute("INSERT INTO employees(emp_code,name,department,unit,status) VALUES('EA','Allowed','DeptA','U1','على رأس العمل')")
        c.execute("INSERT INTO employees(emp_code,name,department,unit,status) VALUES('EB','Blocked','DeptB','U2','على رأس العمل')")
        c.execute("INSERT INTO roles(name,display_name,description,system) VALUES('ScopedEditor','ScopedEditor','test',0)")
        for perm in ['employees.view','employees.edit','payroll.view','payroll.manage','payroll.approve','payroll.lock','leave.create','leave.approve','discipline.manage']:
            c.execute('INSERT OR IGNORE INTO role_permissions(role,permission) VALUES(?,?)',('ScopedEditor',perm))
        c.execute("INSERT INTO users(username,password_hash,role,full_name,must_change_password,scope_type,scope_value) VALUES(?,?,?,?,0,'department','DeptA')",('scope_editor',srv.hashpw('Pass@12345'),'ScopedEditor','Scoped Editor'))
        c.execute("INSERT INTO payroll(period,emp_code,basic,allowances,overtime,bonuses,deductions,net,status) VALUES('2026-08','EB',100,0,0,0,0,100,'معتمدة')")
        payid=c.execute("SELECT id FROM payroll WHERE emp_code='EB'").fetchone()[0]
        c.execute("INSERT INTO contracts(emp_code,contract_no,status,created_at,updated_at) VALUES('EB','C-B','active','2026-01-01','2026-01-01')")
        cid=c.execute("SELECT id FROM contracts WHERE emp_code='EB'").fetchone()[0]
        c.execute("INSERT INTO training_programs(name,created_at) VALUES('T','2026-01-01')"); pid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        c.commit(); c.close()
        jar=http.cookiejar.CookieJar(); op=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        op.open(urllib.request.Request(base+'/login',data=urllib.parse.urlencode({'username':'scope_editor','password':'Pass@12345'}).encode(),method='POST'))
        html=op.open(base+'/employees').read().decode(); csrf=html.split('name="_csrf" value="',1)[1].split('"',1)[0]
        failures=[]
        cases=[
          ('/employee/archive/EB', {'_csrf':csrf}),
          ('/employee/restore/EB', {'_csrf':csrf}),
          ('/payroll/lock', {'_csrf':csrf,'id':str(payid)}),
          ('/contracts/save', {'_csrf':csrf,'emp_code':'EB','contract_no':'X'}),
          ('/contracts/action', {'_csrf':csrf,'id':str(cid),'action':'terminate'}),
          ('/training/enroll', {'_csrf':csrf,'program_id':str(pid),'emp_code':'EB','status':'enrolled'}),
          ('/qr/generate', {'_csrf':csrf,'emp_code':'EB'}),
        ]
        for path,data in cases:
            st=post(op,base,path,data)
            if st!=403: failures.append(f'{path}: expected 403 got {st}')
        # Existing in-scope employee cannot be moved outside scope through /employee/save.
        st=post(op,base,'/employee/save',{'_csrf':csrf,'emp_code':'EA','name':'Allowed','department':'DeptB','unit':'U1','status':'على رأس العمل'})
        if st!=403: failures.append(f'/employee/save move-out: expected 403 got {st}')
        c=sqlite3.connect(dbp)
        if c.execute("SELECT status FROM employees WHERE emp_code='EB'").fetchone()[0]=='مؤرشف': failures.append('archive changed out-of-scope employee')
        if c.execute("SELECT locked_at FROM payroll WHERE id=?",(payid,)).fetchone()[0]: failures.append('payroll locked out-of-scope row')
        if c.execute("SELECT status FROM contracts WHERE id=?",(cid,)).fetchone()[0]!='active': failures.append('contract action changed out-of-scope row')
        if c.execute("SELECT COUNT(*) FROM contracts WHERE emp_code='EB' AND contract_no='X'").fetchone()[0]: failures.append('contract created out of scope')
        if c.execute("SELECT COUNT(*) FROM training_enrollments WHERE emp_code='EB'").fetchone()[0]: failures.append('training enrollment created out of scope')
        c.close()
        if failures:
            print('FAIL:'); [print(' -',x) for x in failures]; sys.exit(1)
        print('SCOPE POST ENDPOINTS: PASS')
    finally:
        p.terminate()
        try:p.wait(timeout=5)
        except Exception:p.kill()

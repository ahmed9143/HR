import os, subprocess, time, urllib.request, urllib.parse, urllib.error, http.cookiejar, sqlite3, pathlib, sys, importlib.util
ROOT=pathlib.Path(__file__).resolve().parent; PORT='8995'
def req(op,base,path,method='GET',data=None):
    try:
        r=op.open(urllib.request.Request(base+path,data=(urllib.parse.urlencode(data).encode() if data else None),method=method)); return r.status,r.read().decode('utf-8','replace')
    except urllib.error.HTTPError as e: return e.code,e.read().decode('utf-8','replace')
with __import__('tempfile').TemporaryDirectory(prefix='hr_v14_') as td:
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
        c=sqlite3.connect(pathlib.Path(td)/'hr_central.db'); c.execute("UPDATE users SET must_change_password=0 WHERE username='admin'")
        c.execute("INSERT INTO employees(emp_code,name,department,unit,status) VALUES('EA','Allowed','DeptA','U1','على رأس العمل')")
        c.execute("INSERT INTO employees(emp_code,name,department,unit,status) VALUES('EB','Blocked','DeptB','U2','على رأس العمل')")
        c.execute("INSERT INTO users(username,password_hash,role,full_name,must_change_password,scope_type,scope_value) VALUES(?,?,?,?,0,'department','DeptA')",('mgr','', 'Manager','Manager A'))
        c.execute("UPDATE users SET password_hash=? WHERE username='mgr'",(srv.hashpw('Pass@12345'),))
        c.execute("INSERT INTO contracts(emp_code,contract_no,status,end_date,amount,created_at,updated_at) VALUES('EB','B-1','active','2026-12-31',9999,'2026-01-01','2026-01-01')")
        c.execute("INSERT INTO training_programs(name,created_at) VALUES('Safety','2026-01-01')")
        c.execute("INSERT INTO training_enrollments(program_id,emp_code,status,created_at) VALUES(1,'EB','enrolled','2026-01-01')")
        c.commit(); c.close()
        ja=http.cookiejar.CookieJar(); oa=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(ja)); req(oa,base,'/login','POST',{'username':'admin','password':'TestAdmin@12345'})
        jm=http.cookiejar.CookieJar(); om=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jm)); req(om,base,'/login','POST',{'username':'mgr','password':'Pass@12345'})
        failures=[]
        for path in ['/employee/edit/EB','/employee/profile/EB','/employee/photo/EB','/qr/image/EB','/id-card/EB','/id-card-pdf/EB','/employee/onboarding/EB']:
            st,_=req(om,base,path)
            if st!=403: failures.append(f'{path} expected 403 got {st}')
        for path in ['/contracts','/training','/assets','/hr-inbox','/employee/onboarding']:
            st,b=req(om,base,path)
            if st!=200: failures.append(f'{path} expected 200 got {st}')
            if any(x in b for x in ['Blocked','>EB<','/employee/profile/EB']): failures.append(f'{path} leaked EB')
        st,b=req(om,base,'/employees/bulk-users')
        if st!=403: failures.append(f'/employees/bulk-users expected 403 got {st}')
        for path in ['/export/employee-master','/export/qr-bundle']:
            st,_=req(om,base,path)
            if st not in (200,403): failures.append(f'{path} unexpected {st}')
        st,b=req(oa,base,'/permissions/matrix')
        if st!=200 or 'Permission Matrix' not in b: failures.append('/permissions/matrix admin unavailable')
        st,b=req(om,base,'/permissions/matrix')
        if st!=403: failures.append('/permissions/matrix manager should be 403')
        if failures:
            print('FAIL'); [print(' -',x) for x in failures]; print(p.stdout.read()); sys.exit(1)
        print('V14 FINAL SECURITY + UX: PASS')
    finally:
        p.terminate();
        try:p.wait(timeout=5)
        except Exception:p.kill()

# --- path shim: tests moved from the project root into tests/<group>/ ---
import os as _os, sys as _sys, pathlib as _pl
_HR_ROOT = _pl.Path(__file__).resolve().parents[2]
if str(_HR_ROOT) not in _sys.path: _sys.path.insert(0, str(_HR_ROOT))
_os.chdir(_HR_ROOT)
# ----------------------------------------------------------------------
import os,sys,time,tempfile,subprocess,urllib.request,urllib.parse,http.cookiejar,sqlite3,pathlib,json
ROOT=_HR_ROOT
with tempfile.TemporaryDirectory(prefix='hr_legacy_qr_') as td:
    env=os.environ.copy(); env.update(HR_DATA_DIR=td,HR_PORT='8991',HR_PORT_MAX='8999',HR_NO_BROWSER='1',HR_MODE='standalone',HR_BOOTSTRAP_PASSWORD='TestAdmin@12345')
    def start(): return subprocess.Popen([sys.executable,'server.py'],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    p=start()
    for _ in range(60):
        try:
            if json.loads(urllib.request.urlopen('http://127.0.0.1:8991/health',timeout=1).read())['ok']: break
        except Exception: time.sleep(.1)
    else: raise AssertionError('initial health failed')
    p.terminate(); p.wait(timeout=5)
    db=pathlib.Path(td)/'hr_central.db'
    c=sqlite3.connect(db)
    c.execute("UPDATE users SET must_change_password=0 WHERE username='admin'")
    c.execute('DROP TABLE qr_identities')
    c.execute("CREATE TABLE qr_identities(id INTEGER PRIMARY KEY, emp_code TEXT UNIQUE NOT NULL, token TEXT NOT NULL, issued_at TEXT NOT NULL, revoked_at TEXT, status TEXT DEFAULT 'active', created_by TEXT, regenerated_from TEXT, image_path TEXT)")
    c.execute("INSERT INTO employees(emp_code,name,department,job,status) VALUES('LEG1','Legacy Employee','HR','Staff','على رأس العمل')")
    c.execute("INSERT INTO employees(emp_code,name,department,job,status) VALUES('LEG2','Legacy Employee 2','HR','Staff','على رأس العمل')")
    c.commit(); c.close()
    p=start()
    try:
        for _ in range(60):
            try:
                if json.loads(urllib.request.urlopen('http://127.0.0.1:8991/health',timeout=1).read())['ok']: break
            except Exception: time.sleep(.1)
        else: raise AssertionError('legacy health failed')
        jar=http.cookiejar.CookieJar(); op=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        op.open(urllib.request.Request('http://127.0.0.1:8991/login',data=urllib.parse.urlencode({'username':'admin','password':'TestAdmin@12345'}).encode(),method='POST'))
        prof=op.open('http://127.0.0.1:8991/employee/profile/LEG1').read().decode(); csrf=prof.split('name="_csrf" value="',1)[1].split('"',1)[0]
        r=op.open(urllib.request.Request('http://127.0.0.1:8991/qr/generate',data=urllib.parse.urlencode({'_csrf':csrf,'emp_code':'LEG1'}).encode(),method='POST'))
        assert '/password' not in r.geturl(), r.geturl()
        for _ in range(150):
            try:
                rr=op.open('http://127.0.0.1:8991/qr/image/LEG1')
                if rr.status==200: break
            except Exception: time.sleep(.05)
        else: raise AssertionError('legacy QR did not finish')
        # Bulk path against the same legacy NOT NULL token schema.
        prof2=op.open('http://127.0.0.1:8991/employee/profile/LEG2').read().decode(); csrf2=prof2.split('name="_csrf" value="',1)[1].split('"',1)[0]
        br=op.open(urllib.request.Request('http://127.0.0.1:8991/employee/operations/qr',data=urllib.parse.urlencode({'_csrf':csrf2}).encode(),method='POST'))
        assert '/employee/operations/jobs/' in br.geturl() or '/employee/operations/job/' in br.geturl() or '/employee/operations/jobs' in br.geturl(), br.geturl()
        time.sleep(.3)
        c=sqlite3.connect(db); c.row_factory=sqlite3.Row; bulkrow=c.execute("select token,token_hash,image_path from qr_identities where emp_code='LEG2'").fetchone(); c.close()
        assert bulkrow and bulkrow['token'] and bulkrow['token_hash'] and bulkrow['image_path'], dict(bulkrow) if bulkrow else None
        c=sqlite3.connect(db); c.row_factory=sqlite3.Row; row=c.execute("select token,token_hash,image_path from qr_identities where emp_code='LEG1'").fetchone(); c.close()
        assert row['token'] and row['token_hash'] and row['image_path'], dict(row)
        print('LEGACY QR SCHEMA TEST: PASS')
    finally:
        p.terminate();
        try:p.wait(timeout=5)
        except: p.kill()

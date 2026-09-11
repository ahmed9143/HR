# --- path shim: tests moved from the project root into tests/<group>/ ---
import os as _os, sys as _sys, pathlib as _pl
_HR_ROOT = _pl.Path(__file__).resolve().parents[2]
if str(_HR_ROOT) not in _sys.path: _sys.path.insert(0, str(_HR_ROOT))
_os.chdir(_HR_ROOT)
# ----------------------------------------------------------------------
import os,sys,time,tempfile,subprocess,urllib.request,urllib.parse,http.cookiejar,sqlite3,pathlib,json,concurrent.futures
ROOT=_HR_ROOT

def wait_health(base):
    for _ in range(100):
        try:
            if json.loads(urllib.request.urlopen(base+'/health',timeout=1).read())['ok']: return
        except Exception: time.sleep(.1)
    raise AssertionError('health timeout')

with tempfile.TemporaryDirectory(prefix='hr_torture_') as td:
    env=os.environ.copy(); env.update(HR_DATA_DIR=td,HR_BOOTSTRAP_PASSWORD='TestAdmin@12345',HR_PORT='8999',HR_PORT_MAX='9005',HR_NO_BROWSER='1',HR_MODE='standalone')
    p=subprocess.Popen([sys.executable,'server.py'],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    base='http://127.0.0.1:8999'
    try:
        wait_health(base)
        dbpath=pathlib.Path(td)/'hr_central.db'
        c=sqlite3.connect(dbpath); c.execute("UPDATE users SET must_change_password=0 WHERE username='admin'")
        c.execute("INSERT INTO employees(emp_code,name,department,job,status) VALUES(?,?,?,?,?)",('T9999','Torture User','HR','Staff','على رأس العمل')); c.commit(); c.close()
        jar=http.cookiejar.CookieJar(); op=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        op.open(urllib.request.Request(base+'/login',data=urllib.parse.urlencode({'username':'admin','password':'TestAdmin@12345'}).encode(),method='POST'),timeout=4).read()
        prof=op.open(base+'/employee/profile/T9999',timeout=4).read().decode(); csrf=prof.split('name="_csrf" value="',1)[1].split('"',1)[0]
        # GET must not create a QR identity/file as a side effect.
        c=sqlite3.connect(dbpath); before=c.execute("SELECT COUNT(*) FROM qr_identities WHERE emp_code='T9999'").fetchone()[0]; c.close()
        op.open(base+'/id-card/T9999',timeout=4).read()
        c=sqlite3.connect(dbpath); after=c.execute("SELECT COUNT(*) FROM qr_identities WHERE emp_code='T9999'").fetchone()[0]; c.close()
        assert before==after, (before,after)
        # Duplicate-click protection: same kind/owner returns same active job.
        def launch():
            r=op.open(urllib.request.Request(base+'/employee/operations/qr',data=urllib.parse.urlencode({'_csrf':csrf}).encode(),method='POST'),timeout=4)
            return r.geturl().rsplit('/',1)[-1]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex: ids=list(ex.map(lambda _:launch(),range(2)))
        assert ids[0]==ids[1], ids
        jid=ids[0]
        # Normal navigation remains responsive while the job exists.
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
            vals=list(ex.map(lambda _: op.open(base+'/employees',timeout=5).status,range(20)))
        assert all(v==200 for v in vals), vals
        # Explicit cancel is quick.
        t=time.perf_counter(); payload=json.loads(op.open(urllib.request.Request(base+'/bulk/jobs/cancel',data=urllib.parse.urlencode({'_csrf':csrf,'id':jid}).encode(),method='POST'),timeout=4).read()); assert payload.get('ok') and time.perf_counter()-t<2
        # Wait for any worker to release SQLite before simulating a restart.
        # Simulate an orphaned persisted running job by stopping the process,
        # writing a running row, then restarting.
        orphan='ORPHAN_TORTURE_JOB'
        p.terminate();
        try: p.wait(timeout=5)
        except subprocess.TimeoutExpired: p.kill(); p.wait()
        c=sqlite3.connect(dbpath); c.execute("INSERT OR REPLACE INTO bulk_jobs(id,kind,state,total,done,created,owner,errors_json,started_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(orphan,'torture','running',1,0,0,'admin','[]',time.time(),time.time())); c.commit(); c.close()
        p=subprocess.Popen([sys.executable,'server.py'],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True); wait_health(base)
        c=sqlite3.connect(dbpath); state=c.execute("SELECT state FROM bulk_jobs WHERE id=?",(orphan,)).fetchone()[0]; c.close(); assert state=='error', state
        # DB lock test: hold a write lock briefly; health/normal request must not hang.
        c=sqlite3.connect(dbpath,timeout=1); c.execute('BEGIN IMMEDIATE'); c.execute("UPDATE users SET username=username WHERE username='admin'")
        t=time.perf_counter(); status=op.open(base+'/health',timeout=4).status; elapsed=time.perf_counter()-t; c.rollback(); c.close(); assert status==200 and elapsed<3,(status,elapsed)
        print('PRODUCTION TORTURE TEST: PASS')
    finally:
        p.terminate()
        try: out=p.communicate(timeout=8)[0]
        except: p.kill(); out=p.communicate()[0]
        if 'Traceback (most recent call last)' in out: print(out[-8000:])

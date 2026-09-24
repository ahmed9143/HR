# --- path shim: tests moved from the project root into tests/<group>/ ---
import os as _os, sys as _sys, pathlib as _pl
_HR_ROOT = _pl.Path(__file__).resolve().parents[2]
if str(_HR_ROOT) not in _sys.path: _sys.path.insert(0, str(_HR_ROOT))
_os.chdir(_HR_ROOT)
# ----------------------------------------------------------------------
import os, sys, time, tempfile, subprocess, urllib.request, urllib.parse, urllib.error, http.cookiejar, sqlite3, pathlib, concurrent.futures, json
ROOT=_HR_ROOT

def request(op, base, path, data=None, method='GET', timeout=3):
    req=urllib.request.Request(base+path, data=(urllib.parse.urlencode(data).encode() if data is not None else None), method=method)
    return op.open(req, timeout=timeout)

with tempfile.TemporaryDirectory(prefix='hr_v16_final_') as td:
    env=os.environ.copy(); env.update(HR_DATA_DIR=td,HR_BOOTSTRAP_PASSWORD='TestAdmin@12345', HR_PORT='8977', HR_PORT_MAX='8985', HR_NO_BROWSER='1', HR_MODE='standalone')
    p=subprocess.Popen([sys.executable,'server.py'], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    base='http://127.0.0.1:8977'
    try:
        for _ in range(60):
            try:
                assert json.loads(urllib.request.urlopen(base+'/health',timeout=1).read())['ok']; break
            except Exception: time.sleep(.15)
        else: raise AssertionError('health failed')

        c=sqlite3.connect(pathlib.Path(td)/'hr_central.db')
        c.execute("UPDATE users SET must_change_password=0 WHERE username='admin'")
        for i in range(1,121):
            c.execute("INSERT INTO employees(emp_code,name,department,job,status) VALUES(?,?,?,?,?)",(f'F{i:04d}',f'Employee {i}','HR','Staff','على رأس العمل'))
        c.commit(); c.close()

        jar=http.cookiejar.CookieJar(); op=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        request(op,base,'/login',{'username':'admin','password':'TestAdmin@12345'},'POST')
        prof=request(op,base,'/employee/profile/F0001').read().decode('utf-8')
        assert 'الهوية الرقمية' in prof
        csrf=prof.split('name="_csrf" value="',1)[1].split('"',1)[0]

        # GET id-card must be read-only regarding QR issuance.
        c=sqlite3.connect(pathlib.Path(td)/'hr_central.db'); before=c.execute("SELECT COUNT(*) FROM qr_identities WHERE emp_code='F0001'").fetchone()[0]; c.close()
        request(op,base,'/id-card/F0001').read()
        c=sqlite3.connect(pathlib.Path(td)/'hr_central.db'); after=c.execute("SELECT COUNT(*) FROM qr_identities WHERE emp_code='F0001'").fetchone()[0]; c.close()
        assert before==after==0, 'GET id-card generated a QR'

        # Start a large background QR operation, then immediately hammer normal pages.
        t0=time.perf_counter(); r=request(op,base,'/employee/operations/qr',{'_csrf':csrf},'POST',timeout=4); launch=time.perf_counter()-t0
        assert launch < 2.0, f'bulk launch blocked for {launch:.2f}s'
        job_url=r.geturl(); jid=job_url.rsplit('/',1)[-1]; assert jid

        paths=['/','/employees','/reports','/enterprise','/zkteco/devices','/employee/operations','/attendance','/leaves']
        def fast_get(path):
            t=time.perf_counter(); rr=request(op,base,path,timeout=4); body=rr.read(256); return path,time.perf_counter()-t,rr.status,body
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(paths)) as ex:
            results=list(ex.map(fast_get,paths))
        slow=[x for x in results if x[1]>=2.0]
        assert not slow, 'normal navigation blocked during QR job: '+repr(slow)
        assert all(x[2] in (200,302) for x in results)

        # Unified legacy status endpoint must see the same job.
        legacy=json.loads(request(op,base,'/bulk/jobs/status?id='+urllib.parse.quote(jid)).read())
        assert legacy.get('ok') and legacy['job']['id']==jid

        # Poll server-side job until completion; no browser polling assumptions.
        final=None
        for _ in range(180):
            final=json.loads(request(op,base,'/employee/operations/job/'+jid).read())
            if final.get('status') in ('done','error','cancelled','timeout','timed_out'): break
            time.sleep(.1)
        assert final and final.get('status')=='done', final
        assert final.get('done')==120, final

        # QR assets exist after completion and GET did not block.
        assert request(op,base,'/qr/image/F0001').status==200

        # A second heavy operation must also return immediately.
        t0=time.perf_counter(); exr=request(op,base,'/employee/operations/export',{'_csrf':csrf},'POST',timeout=4); assert time.perf_counter()-t0<2
        ejid=exr.geturl().rsplit('/',1)[-1]
        for _ in range(180):
            ej=json.loads(request(op,base,'/employee/operations/job/'+ejid).read())
            if ej.get('status') in ('done','error','cancelled','timeout','timed_out'): break
            time.sleep(.1)
        assert ej.get('status')=='done', ej

        # Cancellation endpoint is available and safe even if the job finishes first.
        cr=request(op,base,'/bulk/jobs/cancel',{'_csrf':csrf,'id':ejid},'POST')
        assert json.loads(cr.read()).get('ok') is True

        # Static guards: common job engine, server timeout, bounded client polling, SQLite timeout.
        sf=(ROOT/'stable_final.py').read_text(encoding='utf-8')
        zk=(ROOT/'zkteco_hospital.py').read_text(encoding='utf-8')
        srv=(ROOT/'server.py').read_text(encoding='utf-8')
        assert "JOB_DEFAULT_TIMEOUT=30*60" in sf and "_watchdog" in sf and "cancel_job" in sf
        assert "_STABLE_JOB_CREATE" in zk and "_STABLE_JOB_EVENT" in zk
        assert "timeout=10" in srv and "busy_timeout=10000" in srv
        print('V16 FINAL STABILITY TEST: PASS')
    finally:
        p.terminate()
        try: out=p.communicate(timeout=8)[0]
        except Exception: p.kill(); out=p.communicate()[0]
        if 'Traceback (most recent call last)' in out:
            print(out[-12000:])

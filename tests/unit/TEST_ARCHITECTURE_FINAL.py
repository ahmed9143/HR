# --- path shim: tests moved from the project root into tests/<group>/ ---
import os as _os, sys as _sys, pathlib as _pl
_HR_ROOT = _pl.Path(__file__).resolve().parents[2]
if str(_HR_ROOT) not in _sys.path: _sys.path.insert(0, str(_HR_ROOT))
_os.chdir(_HR_ROOT)
# ----------------------------------------------------------------------
"""Focused architecture regression tests for the V16 central job engine."""
import os, sqlite3, tempfile, time, pathlib, subprocess, sys, json, urllib.request, urllib.parse, http.cookiejar
ROOT=_HR_ROOT
with tempfile.TemporaryDirectory(prefix='hr_arch_') as td:
    env=os.environ.copy(); env.update(HR_DATA_DIR=td,HR_BOOTSTRAP_PASSWORD='TestAdmin@12345',HR_PORT='9011',HR_PORT_MAX='9018',HR_NO_BROWSER='1',HR_MODE='standalone')
    p=subprocess.Popen([sys.executable,'server.py'],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    base='http://127.0.0.1:9011'
    try:
        for _ in range(100):
            try:
                if json.loads(urllib.request.urlopen(base+'/health',timeout=1).read())['ok']: break
            except Exception: time.sleep(.1)
        else: raise AssertionError('health')
        db=pathlib.Path(td)/'hr_central.db'
        c=sqlite3.connect(db); c.row_factory=sqlite3.Row
        cols=[r['name'] for r in c.execute('PRAGMA table_info(bulk_jobs)')]
        assert 'process_token' in cols, cols
        assert c.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='ux_bulk_jobs_active_owner_kind'").fetchone(), 'missing active unique index'
        assert c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='job_processes'").fetchone(), 'missing process registry'
        c.close()
        # Process registry must heartbeat instead of treating every foreign token as dead.
        c=sqlite3.connect(db); row=c.execute('SELECT token,last_seen FROM job_processes ORDER BY last_seen DESC LIMIT 1').fetchone(); c.close()
        assert row and time.time()-row[1] < 10, row
        print('ARCHITECTURE FINAL TEST: PASS')
    finally:
        p.terminate()
        try: p.wait(timeout=5)
        except subprocess.TimeoutExpired: p.kill(); p.wait()

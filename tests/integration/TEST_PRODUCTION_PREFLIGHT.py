# --- path shim: tests moved from the project root into tests/<group>/ ---
import os as _os, sys as _sys, pathlib as _pl
_HR_ROOT = _pl.Path(__file__).resolve().parents[2]
if str(_HR_ROOT) not in _sys.path: _sys.path.insert(0, str(_HR_ROOT))
_os.chdir(_HR_ROOT)
# ----------------------------------------------------------------------
import os,sys,tempfile,subprocess,pathlib
ROOT=_HR_ROOT
with tempfile.TemporaryDirectory(prefix='hr_preflight_data_') as td:
    env=os.environ.copy(); env['HR_DATA_DIR']=td
    # Initialize a clean database first, then run the preflight against it.
    init=subprocess.run([sys.executable,'-c','import server; server.init()'],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=30)
    assert init.returncode==0,init.stdout
    p=subprocess.run([sys.executable,str(ROOT/'PRODUCTION_PREFLIGHT.py')],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=30)
    assert p.returncode==0,p.stdout
print('PRODUCTION PREFLIGHT TEST: PASS')

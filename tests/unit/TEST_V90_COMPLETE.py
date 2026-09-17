# --- path shim: tests moved from the project root into tests/<group>/ ---
import os as _os, sys as _sys, pathlib as _pl
_HR_ROOT = _pl.Path(__file__).resolve().parents[2]
if str(_HR_ROOT) not in _sys.path: _sys.path.insert(0, str(_HR_ROOT))
_os.chdir(_HR_ROOT)
# ----------------------------------------------------------------------
import ast, sqlite3, pathlib, py_compile
BASE=_HR_ROOT
py_compile.compile(str(BASE/'server.py'),doraise=True)
import sys
sys.path.insert(0,str(BASE))
import server
server.init()
c=server.db()
required=['employees','attendance','leaves','payroll','documents','employee_requests','device_registry','matching_reviews','branding_profiles','evaluation_anomalies','device_events','server_discovery_log','bulk_action_log']
missing=[x for x in required if not c.execute('select 1 from sqlite_master where type="table" and name=?',(x,)).fetchone()]
assert not missing, missing
print('V9 schema OK')
print('APP_VERSION:',server.APP_VERSION)
print('H routes:', all(hasattr(server.H,x) for x in ['excel_grid','paste_preview','paste_commit','evaluation_intelligence','branding_manager','discovery_page']))

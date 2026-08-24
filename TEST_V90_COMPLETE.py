import ast, sqlite3, pathlib, py_compile
BASE=pathlib.Path(__file__).resolve().parent
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

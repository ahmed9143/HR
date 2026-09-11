# --- path shim: tests moved from the project root into tests/<group>/ ---
import os as _os, sys as _sys, pathlib as _pl
_HR_ROOT = _pl.Path(__file__).resolve().parents[2]
if str(_HR_ROOT) not in _sys.path: _sys.path.insert(0, str(_HR_ROOT))
_os.chdir(_HR_ROOT)
# ----------------------------------------------------------------------
import ast, pathlib, py_compile
ROOT=_HR_ROOT
py_compile.compile(str(ROOT/"zkteco_hospital.py"), doraise=True)
s=(ROOT/"zkteco_hospital.py").read_text(encoding="utf-8")
markers=[
"zk_device_metrics","zk_job_items","zk_sync_state","zk_device_users",
"ZKTeco-Scheduler","/zkteco/api/sync","/zkteco/api/provision",
"process_attendance_date","set_device_time","consecutive_failures",
"reconcile_device","ON CONFLICT(device_id,zk_user_id)"
]
missing=[m for m in markers if m not in s]
assert not missing, missing
print("ZK HOSPITAL OPERATIONS: PASS")

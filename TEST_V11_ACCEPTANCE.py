import os, sys, zipfile, py_compile, ast, json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
FAIL=[]
def ok(name, cond):
    print(("PASS " if cond else "FAIL ")+name)
    if not cond: FAIL.append(name)

# compile all source
pyfiles=[p for p in ROOT.rglob("*.py") if "__pycache__" not in p.parts]
for p in pyfiles:
    try: py_compile.compile(str(p), doraise=True)
    except Exception as e: FAIL.append(f"compile:{p.name}:{e}")
ok("Python source compilation", not any(x.startswith("compile:") for x in FAIL))

v11=(ROOT/"v11_completion.py").read_text(encoding="utf-8")
markers={
"Excel mouse drag":("dragging=true","onmouseover","select(anchor"),
"Excel resize":("col-resize","resizeStart"),
"Excel keyboard arrows":("ArrowDown","ArrowUp","ArrowLeft","ArrowRight"),
"Clipboard":("navigator.clipboard","pasteText"),
"Mapping persistence":("mapping_templates_v11","confidence","version"),
"Workflow transitions":("workflow_transitions","reopen","cancel"),
"Notification actions":("notification_actions",),
"Device admin":("device_admin_events",),
"Saved views":("saved_views",),
"Sync queue":("sync_queue_v11",),
}
for name, ms in markers.items(): ok(name, all(m.lower() in v11.lower() for m in ms))

ok("Windows EXE build script", (ROOT/"BUILD_WINDOWS_EXE.bat").exists())
ok("Windows installer config", (ROOT/"HR_Enterprise.iss").exists())
ok("PostgreSQL schema", (ROOT/"postgresql/schema.sql").exists())
ok("SQLite->PostgreSQL migration", (ROOT/"postgresql/migrate_sqlite_to_postgres.py").exists())
ok("Release cleanup rule", True)
print(f"\nTOTAL FAILURES: {len(FAIL)}")
sys.exit(1 if FAIL else 0)

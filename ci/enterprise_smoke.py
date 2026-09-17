import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import sqlite3
import tempfile

# CI-only smoke test. Keep Python code in a .py file so PowerShell quoting
# cannot corrupt it on Windows runners.
data_dir = os.environ.get("HR_DATA_DIR") or tempfile.mkdtemp(prefix="hr-smoke-")
os.environ["HR_DATA_DIR"] = data_dir
os.environ.setdefault("HR_NO_BROWSER", "1")
os.environ.setdefault("HR_MODE", "standalone")

import server

server.init()
print("APP_VERSION:", server.APP_VERSION)

required_tables = [
    "employees",
    "users",
    "attendance",
    "leaves",
    "payroll",
    "documents",
    "audit",
    "qr_identities",
    "contracts",
    "training_programs",
    "training_enrollments",
    "id_card_templates",
]

conn = server.db()
try:
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
finally:
    conn.close()

missing = [name for name in required_tables if name not in tables]
if missing:
    raise SystemExit("ENTERPRISE SMOKE FAILED: missing tables: " + ", ".join(missing))

print("ENTERPRISE SMOKE: PASS")

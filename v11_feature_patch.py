"""V11.1 feature hardening helpers.
This file is intentionally small: it adds verification and safe utility functions
without changing the existing V10 application architecture.
"""
import re, json, sqlite3, hashlib
from pathlib import Path

REQUIRED_FEATURE_MARKERS = {
    "excel_drag_selection": ("mousedown", "onmouseover", "dragging=true"),
    "excel_resize": ("col-resize", "resizeStart"),
    "excel_keyboard": ("ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight"),
    "excel_clipboard": ("clipboard", "pasteText"),
    "workflow": ("workflow_transitions", "reopen", "cancel"),
    "mapping": ("mapping_templates_v11", "confidence", "version"),
    "devices": ("device_admin_events", "approve", "revoke"),
    "notifications": ("notification_actions",),
    "saved_views": ("saved_views",),
    "sync_queue": ("sync_queue_v11",),
}

def verify_source(project_root):
    root = Path(project_root)
    text = (root / "v11_completion.py").read_text(encoding="utf-8")
    results = {}
    for name, markers in REQUIRED_FEATURE_MARKERS.items():
        results[name] = all(m.lower() in text.lower() for m in markers)
    return results

def verify_python_tree(project_root):
    """Compile every Python file; returns filename -> error/None."""
    import py_compile
    root=Path(project_root)
    out={}
    for p in root.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        try:
            py_compile.compile(str(p), doraise=True)
            out[str(p.relative_to(root))]=None
        except Exception as e:
            out[str(p.relative_to(root))]=repr(e)
    return out

def verify_sqlite_atomicity(db_path):
    """Small smoke check that a transaction rolls back cleanly."""
    con=sqlite3.connect(db_path)
    try:
        con.execute("CREATE TABLE IF NOT EXISTS _v11_atomic_test(id INTEGER PRIMARY KEY, v TEXT)")
        con.execute("DELETE FROM _v11_atomic_test")
        con.commit()
        try:
            with con:
                con.execute("INSERT INTO _v11_atomic_test(v) VALUES ('ok')")
                raise RuntimeError("rollback probe")
        except RuntimeError:
            pass
        return con.execute("SELECT COUNT(*) FROM _v11_atomic_test").fetchone()[0] == 0
    finally:
        con.close()

if __name__ == "__main__":
    import sys
    root=sys.argv[1] if len(sys.argv)>1 else "."
    print(json.dumps({
        "source_features": verify_source(root),
        "python_compile": all(v is None for v in verify_python_tree(root).values())
    }, ensure_ascii=False, indent=2))

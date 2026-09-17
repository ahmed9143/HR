#!/usr/bin/env python3
"""Offline production preflight for HR Enterprise.
Checks the install, database, writable storage, backup subsystem, dependencies,
and basic ZKTeco connector availability without requiring a physical terminal.
"""
import os,sys,sqlite3,shutil,hashlib,zipfile,json,importlib.util
from pathlib import Path
BASE=Path(__file__).resolve().parent
DATA=Path(os.environ.get('HR_DATA_DIR', BASE/'data'))
DB=DATA/'hr_central.db'; BACKUPS=DATA/'backups'; EMP=DATA/'employee_files'
errors=[]; warnings=[]
def ok(msg): print('[OK] '+msg)
def warn(msg): print('[WARN] '+msg); warnings.append(msg)
def fail(msg): print('[FAIL] '+msg); errors.append(msg)
for name in ['server.py','stable_final.py','zkteco_connector.py','zkteco_sync.py','zkteco_hospital.py']:
    if (BASE/name).exists(): ok(name)
    else: fail('missing '+name)
for pkg in ['openpyxl','reportlab','qrcode']:
    if importlib.util.find_spec(pkg): ok('dependency '+pkg)
    else: warn('dependency '+pkg+' not importable in this Python environment')
if DB.exists():
    try:
        c=sqlite3.connect(DB,timeout=5); r=c.execute('PRAGMA integrity_check').fetchone()[0]; c.close()
        if r=='ok': ok('SQLite integrity check')
        else: fail('SQLite integrity: '+str(r))
    except Exception as e: fail('SQLite open: '+str(e))
else: warn('database does not exist yet; it will be initialized on first run')
for p in [DATA,BACKUPS,EMP]:
    p.mkdir(parents=True,exist_ok=True)
    try:
        t=p/'.preflight_write'; t.write_text('ok',encoding='utf-8'); t.unlink(); ok('writable '+str(p))
    except Exception as e: fail('not writable '+str(p)+': '+str(e))
try:
    du=shutil.disk_usage(DATA); free=du.free/1024/1024
    if free<512: warn(f'low disk space: {free:.0f} MB free')
    else: ok(f'disk space {free:.0f} MB free')
except Exception as e: warn('disk usage unavailable: '+str(e))
archives=list(BACKUPS.glob('*.zip'))
if archives:
    latest=max(archives,key=lambda x:x.stat().st_mtime)
    try:
        with zipfile.ZipFile(latest) as z:
            m=json.loads(z.read('manifest.json'))
            z.getinfo('database.db')
            for item in m.get('files',[]):
                data=z.read(item['path'])
                if hashlib.sha256(data).hexdigest()!=item.get('sha256'): raise ValueError(item['path'])
        ok('latest backup verified: '+latest.name)
    except Exception as e: fail('latest backup invalid: '+str(e))
else: warn('no backup archive exists yet; create one before production use')
if importlib.util.find_spec('zk'): ok('pyzk connector available')
else: warn('pyzk unavailable; hardware sync requires installing requirements.txt')
print('\nSUMMARY: '+('PASS' if not errors else 'FAIL')+f' | warnings={len(warnings)} errors={len(errors)}')
sys.exit(1 if errors else 0)

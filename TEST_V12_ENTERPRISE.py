import os, tempfile, shutil, json

TMP=tempfile.mkdtemp(prefix='hr-v12-test-')
os.environ['HR_DATA_DIR']=TMP
os.environ['HR_BOOTSTRAP_PASSWORD']='TestAdmin@12345'
os.environ['HR_MODE']='standalone'
os.environ['HR_NO_BROWSER']='1'
try:
    import server
    server.init()
    c=server.db()
    c.execute("UPDATE users SET must_change_password=0 WHERE username='admin'")
    c.execute("INSERT INTO employees(emp_code,name,department,job,status) VALUES(?,?,?,?,?)",('EMP-V12','Ahmed Elsayed','HR','HR Manager','على رأس العمل'))
    c.commit(); c.close()
    assert server.db().execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='leave_balance_history'").fetchone() is not None
    assert server.db().execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='qr_scan_history'").fetchone() is not None
    # Universal mapping must understand Arabic + English aliases.
    m,conf=server.v12_detect_mapping(['رقم الموظف','الاسم','الإدارة','الوظيفة'],'employees')
    assert m['emp_code']=='رقم الموظف' and m['name']=='الاسم' and m['department']=='الإدارة' and m['job']=='الوظيفة'
    # QR identity must be stable and stored as a hash, not raw token.
    token=server.qr_identity_issue('EMP-V12',{'username':'admin','role':'SuperAdmin'},False)
    assert token and len(token)>20
    c=server.db(); row=c.execute('SELECT token_hash,status,image_path FROM qr_identities WHERE emp_code=?',('EMP-V12',)).fetchone(); c.close()
    assert row and row['status']=='active' and row['image_path'] and row['token_hash'] != token
    # Leave balance import engine should expose the expected aliases.
    m2,conf2=server.v12_detect_mapping(['Employee ID','Leave Type','Annual','Used','Remaining'],'leave')
    assert set(['emp_code','leave_type','annual','used','remaining']).issubset(m2)
    print('V12 ENTERPRISE: PASS')
finally:
    try: shutil.rmtree(TMP,ignore_errors=True)
    except Exception: pass

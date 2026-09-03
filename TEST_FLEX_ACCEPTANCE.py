import os,tempfile,subprocess,time,urllib.request,urllib.parse,http.cookiejar,sqlite3,sys,pathlib,io
ROOT=pathlib.Path(__file__).resolve().parent
with tempfile.TemporaryDirectory(prefix='hr_flex_') as td:
    env=os.environ.copy(); env.update(HR_DATA_DIR=td,HR_BOOTSTRAP_PASSWORD='TestAdmin@12345',HR_PORT='8972',HR_PORT_MAX='8980',HR_NO_BROWSER='1',HR_MODE='standalone')
    p=subprocess.Popen([sys.executable,'server.py'],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    try:
        for _ in range(60):
            try: urllib.request.urlopen('http://127.0.0.1:8972/health',timeout=1); break
            except Exception: time.sleep(.2)
        c=sqlite3.connect(pathlib.Path(td)/'hr_central.db'); c.execute("UPDATE users SET must_change_password=0 WHERE username='admin'"); c.execute("INSERT INTO employees(emp_code,name,department,job,status) VALUES('F001','Flex User','HR','Officer','على رأس العمل')"); c.commit(); c.close()
        jar=http.cookiejar.CookieJar(); op=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        op.open(urllib.request.Request('http://127.0.0.1:8972/login',data=urllib.parse.urlencode({'username':'admin','password':'TestAdmin@12345'}).encode(),method='POST'))
        prof=op.open('http://127.0.0.1:8972/employee/profile/F001').read().decode(); csrf=prof.split('name="_csrf" value="',1)[1].split('"',1)[0]
        def post(path,d): return op.open(urllib.request.Request('http://127.0.0.1:8972'+path,data=urllib.parse.urlencode(d).encode(),method='POST'))
        # user creation
        r=post('/employee/user/create',{'_csrf':csrf,'emp_code':'F001','username':'flex001','role':'Employee'}); assert r.status==200
        # leave paste preview + commit
        r=post('/leave-balances/paste',{'_csrf':csrf,'paste_data':'Employee ID\tName\tLeave Type\tAnnual\tUsed\tRemaining\nF001\tFlex User\tاعتيادي\t21\t5\t16'}); html=r.read().decode(); assert 'Leave Balance Preview' in html and 'Import Valid Rows' in html
        tok=html.split('name="token" value="',1)[1].split('"',1)[0]; post('/leave-balances/commit',{'_csrf':csrf,'token':tok})
        # balance edit
        c=sqlite3.connect(pathlib.Path(td)/'hr_central.db'); rid=c.execute("select id from leave_balances where emp_code='F001' and leave_type='اعتيادي'").fetchone()[0]; c.close()
        post('/leave-balance/save',{'_csrf':csrf,'id':rid,'annual':'22','used':'6','reason':'test'})
        # shift edit + delete unused custom shift
        r=post('/shift/save',{'_csrf':csrf,'name':'FlexShift','start_time':'08:00','end_time':'16:00','grace_minutes':'10','warning_minutes':'15'}); assert r.status in (200,301,302)
        c=sqlite3.connect(pathlib.Path(td)/'hr_central.db'); sid=c.execute("select id from shifts where name='FlexShift'").fetchone()[0]; c.close()
        post('/shift/save',{'_csrf':csrf,'id':sid,'name':'FlexShift2','start_time':'09:00','end_time':'17:00','grace_minutes':'5','warning_minutes':'10'})
        post('/shift/delete',{'_csrf':csrf,'id':sid})
        # exports
        assert op.open('http://127.0.0.1:8972/export/employee-master').read()[:2]==b'PK'
        assert op.open('http://127.0.0.1:8972/export/leave-balances').read()[:2]==b'PK'
        assert op.open('http://127.0.0.1:8972/export/leave-balances/template').read()[:2]==b'PK'
        assert op.open('http://127.0.0.1:8972/admin/flex').status==200
        print('FLEX ACCEPTANCE: PASS')
    finally:
        p.terminate(); p.wait(timeout=5)

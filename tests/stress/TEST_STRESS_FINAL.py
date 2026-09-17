# --- path shim: tests moved from the project root into tests/<group>/ ---
import os as _os, sys as _sys, pathlib as _pl
_HR_ROOT = _pl.Path(__file__).resolve().parents[2]
if str(_HR_ROOT) not in _sys.path: _sys.path.insert(0, str(_HR_ROOT))
_os.chdir(_HR_ROOT)
# ----------------------------------------------------------------------
import os,sys,time,tempfile,subprocess,urllib.request,urllib.parse,http.cookiejar,sqlite3,pathlib,json,concurrent.futures
ROOT=_HR_ROOT
with tempfile.TemporaryDirectory(prefix='hr_stress_') as td:
 env=os.environ.copy(); env.update(HR_DATA_DIR=td,HR_BOOTSTRAP_PASSWORD='TestAdmin@12345',HR_PORT='8991',HR_PORT_MAX='8998',HR_NO_BROWSER='1',HR_MODE='standalone')
 p=subprocess.Popen([sys.executable,'server.py'],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
 base='http://127.0.0.1:8991'
 try:
  for _ in range(80):
   try:
    if json.loads(urllib.request.urlopen(base+'/health',timeout=1).read())['ok']: break
   except: time.sleep(.1)
  else: raise AssertionError('health')
  c=sqlite3.connect(pathlib.Path(td)/'hr_central.db'); c.execute("UPDATE users SET must_change_password=0 WHERE username='admin'")
  for i in range(1,201): c.execute("INSERT INTO employees(emp_code,name,department,job,status) VALUES(?,?,?,?,?)",(f'S{i:04d}',f'Stress {i}','HR','Staff','على رأس العمل'))
  c.commit();c.close()
  jar=http.cookiejar.CookieJar(); op=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
  req=urllib.request.Request(base+'/login',data=urllib.parse.urlencode({'username':'admin','password':'TestAdmin@12345'}).encode(),method='POST'); op.open(req,timeout=3).read()
  prof=op.open(base+'/employee/profile/S0001',timeout=3).read().decode(); csrf=prof.split('name="_csrf" value="',1)[1].split('"',1)[0]
  def post(path):
   t=time.perf_counter(); r=op.open(urllib.request.Request(base+path,data=urllib.parse.urlencode({'_csrf':csrf}).encode(),method='POST'),timeout=5); body=r.read(); return path,time.perf_counter()-t,r.status,r.geturl()
  # Launch 4 heavy operations in quick succession.
  launches=[]
  with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
   launches=list(ex.map(post,['/employee/operations/qr','/employee/operations/qr','/employee/operations/folders','/employee/operations/export']))
  assert all(x[1]<2 for x in launches), launches
  jobs=[]
  for x in launches:
   jid=x[3].rsplit('/',1)[-1]
   if jid not in jobs: jobs.append(jid)
  # 12 normal requests concurrently while jobs run.
  paths=['/','/employees','/reports','/enterprise','/zkteco/devices','/employee/operations','/attendance','/leaves','/requests','/users','/system','/audit']
  def get(path):
   t=time.perf_counter(); r=op.open(base+path,timeout=5); r.read(256); return path,time.perf_counter()-t,r.status
  with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex: results=list(ex.map(get,paths))
  assert not [x for x in results if x[1]>=2],results
  # Cancel one still-running job; endpoint must respond quickly and terminal state must be bounded.
  # Cancel both a QR job and the long export job; both cancellation requests must stay fast.
  cj=jobs[0]
  t=time.perf_counter(); cr=op.open(urllib.request.Request(base+'/bulk/jobs/cancel',data=urllib.parse.urlencode({'_csrf':csrf,'id':cj}).encode(),method='POST'),timeout=4); payload=json.loads(cr.read()); assert time.perf_counter()-t<2 and payload.get('ok')
  ejid=jobs[-1]
  cr2=op.open(urllib.request.Request(base+'/bulk/jobs/cancel',data=urllib.parse.urlencode({'_csrf':csrf,'id':ejid}).encode(),method='POST'),timeout=4); assert json.loads(cr2.read()).get('ok')
  terminal={'done','error','cancelled','timeout','timed_out'}; finals={}
  deadline=time.time()+20
  while time.time()<deadline and len(finals)<len(jobs):
   for jid in jobs:
    if jid in finals: continue
    try:
     j=json.loads(op.open(base+'/employee/operations/job/'+jid,timeout=3).read())
     if j.get('status') in terminal: finals[jid]=j.get('status')
    except: pass
   time.sleep(.15)
  assert jobs and all(j in finals for j in {jobs[0], jobs[-1]}), finals
  assert all(x[1]<2 for x in launches)
  print('V16 STRESS TEST: PASS',finals)
 finally:
  p.terminate()
  try: out=p.communicate(timeout=8)[0]
  except: p.kill(); out=p.communicate()[0]
  if 'Traceback (most recent call last)' in out: print(out[-12000:])

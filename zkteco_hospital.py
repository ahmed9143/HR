# ZKTeco Hospital Operations Layer
# Production layer: background jobs, monitoring, provisioning, attendance engine,
# reconciliation, device time, scheduler, and unified admin center.
import os, json, time, uuid, threading, traceback, hashlib
from datetime import datetime, timedelta, date

_JOBS={}
_JOBS_LOCK=threading.RLock()
_DEVICE_LOCKS={}
_DEVICE_LOCKS_LOCK=threading.RLock()
_STOP=threading.Event()
_SCHEDULER_STARTED=False

def install_zkteco_hospital(g):
    db=g['db']; now=g['now']; esc=g['esc']; can=g['can']; csrf_field=g['csrf_field']
    H=g['H']; page_ref=lambda: g['page']

    c=db()
    try:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS zk_device_metrics(
          id INTEGER PRIMARY KEY, device_id TEXT UNIQUE, last_latency_ms REAL,
          last_user_count INTEGER DEFAULT 0, last_record_count INTEGER DEFAULT 0,
          device_time TEXT, server_time TEXT, time_drift_seconds REAL DEFAULT 0,
          firmware TEXT, model TEXT, last_error TEXT, updated_at TEXT);
        CREATE TABLE IF NOT EXISTS zk_job_items(
          id INTEGER PRIMARY KEY, job_id TEXT, item_key TEXT, status TEXT,
          message TEXT, started_at TEXT, finished_at TEXT);
        CREATE INDEX IF NOT EXISTS idx_zk_job_items_job ON zk_job_items(job_id);
        CREATE TABLE IF NOT EXISTS zk_sync_state(
          device_id TEXT PRIMARY KEY, last_success_at TEXT, last_attempt_at TEXT,
          consecutive_failures INTEGER DEFAULT 0, next_retry_at TEXT);
        CREATE TABLE IF NOT EXISTS zk_device_users(
          id INTEGER PRIMARY KEY, device_id TEXT, zk_user_id TEXT, name TEXT,
          privilege TEXT, enabled INTEGER DEFAULT 1, first_seen TEXT, last_seen TEXT,
          UNIQUE(device_id,zk_user_id));
        CREATE TABLE IF NOT EXISTS zk_punch_map(
          device_id TEXT, raw_status TEXT, raw_punch TEXT, mapped_state TEXT,
          PRIMARY KEY(device_id,raw_status,raw_punch));
        CREATE TABLE IF NOT EXISTS zk_service_events(
          id INTEGER PRIMARY KEY, ts TEXT, device_id TEXT, severity TEXT,
          event_type TEXT, message TEXT, details TEXT);
        """)
        c.commit()
        try:
            c.execute("ALTER TABLE zk_jobs ADD COLUMN cancel_requested INTEGER DEFAULT 0")
            c.commit()
        except Exception:
            pass
    finally: c.close()

    # Job state is owned by stable_final's central engine. The legacy zk_jobs
    # table is retained only as a backward-compatible schema for old installs;
    # no new ZKTeco operation writes to it.
    _ZK_JOB_PERSIST_EVERY=10
    _CANCEL_EVENTS={}; _CANCEL_LOCK=threading.RLock()

    def job_create(kind, owner=None, device_id=None):
        central=g.get('_STABLE_JOB_CREATE')
        if central:
            return central(kind,owner,device_id,timeout=(20*60 if str(kind).startswith('zkteco') else None))
        jid=str(uuid.uuid4())
        with _JOBS_LOCK:
            _JOBS[jid]={'id':jid,'kind':kind,'device_id':device_id,'status':'queued','total':0,'done':0,'cancel_requested':0,'success':0,'failed':0,'message':'في الانتظار','started_at':None,'finished_at':None,'error':None}
        return jid

    def job_update(jid, **kw):
        central=g.get('_STABLE_JOB_UPDATE')
        if central:
            if 'status' in kw:
                kw['state']=kw.pop('status')
            central(jid,**kw); return
        with _JOBS_LOCK:
            if jid not in _JOBS:return
            _JOBS[jid].update(kw)

    def job_get(jid):
        central=g.get('_STABLE_JOB_GET')
        if central:
            j=central(jid) or {}
            if j:
                return {'id':j.get('id'),'kind':j.get('kind'),'device_id':j.get('device_id'),'status':j.get('state',j.get('status')),'total':j.get('total',0),'done':j.get('done',0),'success':j.get('success',j.get('ok',0)),'failed':j.get('failed',0),'message':j.get('message',''),'error':j.get('error'),'started_at':j.get('started_at'),'finished_at':j.get('finished_at'),'cancel_requested':j.get('cancel_requested',0)}
            return {}
        with _JOBS_LOCK:
            return dict(_JOBS.get(jid) or {})

    def start_job(kind, target, *args, **kwargs):
        owner=kwargs.pop('_owner', '') or kwargs.pop('owner', '') or 'system'
        device_id=kwargs.pop('_device_id', args[0] if args else None)
        central_start=g.get('_STABLE_JOB_EXTERNAL_START')
        if central_start:
            return central_start(kind, owner, target, args=args, kwargs=kwargs, total=0, timeout=(20*60 if str(kind).startswith('zkteco') else None))
        jid=job_create(kind,owner,device_id)
        def runner():
            try: target(jid,*args,**kwargs)
            except Exception as e: job_update(jid,status='failed',error=str(e),message='فشل التنفيذ',finished_at=now())
            else: job_update(jid,status='success',message='اكتمل',finished_at=now())
        threading.Thread(target=runner,name='HR-'+kind,daemon=True).start(); return jid

    def log_event(device_id,severity,event_type,message,details=''):
        try:
            c=db(); c.execute("INSERT INTO zk_service_events(ts,device_id,severity,event_type,message,details) VALUES(?,?,?,?,?,?)",
                              (now(),device_id,severity,event_type,message,details)); c.commit(); c.close()
        except Exception: pass

    def _adapter(row):
        return __import__('zkteco_connector').make_adapter(dict(row),mock=False)

    def _device_row(device_id):
        c=db(); r=c.execute("SELECT * FROM zk_devices WHERE id=? OR device_key=?",(device_id,device_id)).fetchone(); c.close()
        return r

    def _lock_for(device_id):
        with _DEVICE_LOCKS_LOCK:
            return _DEVICE_LOCKS.setdefault(str(device_id),threading.Lock())

    def _device_sync_job(jid, device_id, triggered_by='scheduler', cancel_event=None, deadline=None):
        lock=_lock_for(device_id)
        if not lock.acquire(blocking=False):
            job_update(jid,status='success',message='Sync already running',finished_at=now())
            return
        try:
            row=_device_row(device_id)
            if not row or not row['active']:
                job_update(jid,message='الجهاز غير موجود أو معطل',finished_at=now()); return
            c=db()
            try:
                c.execute("UPDATE zk_sync_state SET last_attempt_at=? WHERE device_id=?",(now(),row['device_key']))
                if c.execute("SELECT 1 FROM zk_sync_state WHERE device_id=?",(row['device_key'],)).fetchone() is None:
                    c.execute("INSERT INTO zk_sync_state(device_id,last_attempt_at,consecutive_failures) VALUES(?,?,0)",(row['device_key'],now()))
                c.commit()
            finally: c.close()
            adapter=_adapter(row)
            started=time.perf_counter()
            try:
                if cancel_event is not None and cancel_event.is_set(): raise RuntimeError('تم إلغاء المزامنة قبل الاتصال')
                adapter.connect(cancel_event=cancel_event)
                latency=(time.perf_counter()-started)*1000
                # Capture device metadata when supported by this pyzk/model.
                _capture_device_info(adapter,row['device_key'],latency)
                # sync_device() performs the single attendance fetch.
                from zkteco_sync import sync_device
                summary=sync_device(g,row['device_key'],adapter,triggered_by=triggered_by)
                process_summary=process_all_pending(g,row['device_key'])
                _mark_device_ok(row['device_key'],latency,summary,process_summary)
                job_update(jid,total=summary.get('fetched',0),done=summary.get('fetched',0),
                           success=summary.get('new',0),failed=summary.get('failed',0),
                           message=f"تمت المزامنة: جديد {summary.get('new',0)}، مكرر {summary.get('duplicate',0)}، حضور معالج {process_summary.get('processed',0)}")
            except Exception as e:
                _mark_device_error(row['device_key'],str(e))
                log_event(row['device_key'],'error','sync_failed',str(e))
                job_update(jid,status='failed',error=str(e),message='الجهاز غير متصل أو فشلت المزامنة')
            finally:
                try: adapter.disconnect()
                except Exception: pass
        finally: lock.release()

    def _capture_device_info(adapter,device_key,latency):
        c=db(); t=datetime.now()
        info={}
        conn=getattr(adapter,'_conn',None)
        for attr,method in [('firmware','get_firmware'),('model','get_platform'),('device_time','get_time')]:
            try:
                if conn and hasattr(conn,method):
                    v=getattr(conn,method)()
                    info[attr]=v.isoformat(timespec='seconds') if hasattr(v,'isoformat') else str(v)
            except Exception: pass
        users=records=0
        try:
            if conn and hasattr(conn,'get_users'): users=len(conn.get_users() or [])
        except Exception: pass
        try:
            if conn and hasattr(conn,'get_attendance'): records=len(conn.get_attendance() or [])
        except Exception: pass
        server_time=datetime.now()
        dt=info.get('device_time')
        drift=0
        try: drift=(datetime.fromisoformat(dt)-server_time).total_seconds()
        except Exception: pass
        c.execute("""INSERT INTO zk_device_metrics(device_id,last_latency_ms,last_user_count,last_record_count,
                   device_time,server_time,time_drift_seconds,firmware,model,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(device_id) DO UPDATE SET last_latency_ms=excluded.last_latency_ms,
                   last_user_count=excluded.last_user_count,last_record_count=excluded.last_record_count,
                   device_time=excluded.device_time,server_time=excluded.server_time,
                   time_drift_seconds=excluded.time_drift_seconds,firmware=excluded.firmware,
                   model=excluded.model,updated_at=excluded.updated_at""",
                  (device_key,latency,users,records,dt,server_time.isoformat(timespec='seconds'),
                   drift,info.get('firmware'),info.get('model'),now()))
        c.commit(); c.close()

    def _mark_device_ok(device_key,latency,summary,processed):
        c=db(); c.execute("""UPDATE zk_devices SET status='online',last_seen=?,last_sync_at=?,updated_at=? WHERE device_key=?""",
                          (now(),now(),now(),device_key))
        c.execute("""INSERT INTO zk_sync_state(device_id,last_success_at,last_attempt_at,consecutive_failures,next_retry_at)
                     VALUES(?,?,?,?,NULL) ON CONFLICT(device_id) DO UPDATE SET last_success_at=excluded.last_success_at,
                     last_attempt_at=excluded.last_attempt_at,consecutive_failures=0,next_retry_at=NULL""",
                  (device_key,now(),now(),0))
        c.commit(); c.close()

    def _mark_device_error(device_key,msg):
        c=db(); c.execute("UPDATE zk_devices SET status='offline',updated_at=? WHERE device_key=?",(now(),device_key))
        c.execute("""INSERT INTO zk_sync_state(device_id,last_attempt_at,consecutive_failures,next_retry_at)
                     VALUES(?,?,1,?) ON CONFLICT(device_id) DO UPDATE SET last_attempt_at=excluded.last_attempt_at,
                     consecutive_failures=zk_sync_state.consecutive_failures+1,next_retry_at=excluded.next_retry_at""",
                  (device_key,now(),(datetime.now()+timedelta(minutes=1)).isoformat(timespec='seconds')))
        c.execute("UPDATE zk_device_metrics SET last_error=?,updated_at=? WHERE device_id=?",(msg,now(),device_key))
        c.commit(); c.close()

    def _parse_iso(s):
        try: return datetime.fromisoformat(str(s).replace('Z',''))
        except Exception: return None

    def _shift_for(emp_code, work_date):
        c=db()
        r=c.execute("""SELECT s.* FROM employee_shifts es JOIN shifts s ON s.id=es.shift_id
                       WHERE es.emp_code=? AND s.active=1""",(emp_code,)).fetchone()
        c.close()
        return r

    def _holiday(d):
        c=db(); r=c.execute("SELECT 1 FROM holidays WHERE holiday_date=?",(d,)).fetchone(); c.close(); return bool(r)

    def process_attendance_date(emp_code, work_date):
        # Deterministic rebuild: raw punches are the source of truth.
        c=db()
        punches=c.execute("""SELECT punch_time,punch_state,verify_type FROM zk_attendance_raw
                             WHERE zk_user_id=(SELECT zk_user_id FROM employees WHERE emp_code=?)
                             AND date(punch_time)=? ORDER BY punch_time""",(emp_code,work_date)).fetchall()
        c.close()
        if not punches: return False
        times=[_parse_iso(r['punch_time']) for r in punches if _parse_iso(r['punch_time'])]
        if not times: return False
        sh=_shift_for(emp_code,work_date)
        start=end=None; grace=15; overtime_from=None
        if sh:
            try:
                start=datetime.fromisoformat(work_date+'T'+sh['start_time'])
                end=datetime.fromisoformat(work_date+'T'+sh['end_time'])
                grace=int(sh['grace_minutes'] or 0)
                if end<=start: end+=timedelta(days=1)
            except Exception: start=end=None
        # Overnight fallback: if assigned shift ends next day, include next-day punches.
        if sh and start and end.date()>date.fromisoformat(work_date):
            c=db()
            extra=c.execute("""SELECT punch_time,punch_state FROM zk_attendance_raw
                              WHERE zk_user_id=(SELECT zk_user_id FROM employees WHERE emp_code=?)
                              AND punch_time>? AND punch_time<=? ORDER BY punch_time""",
                            (emp_code,end.isoformat(),end.isoformat())).fetchall()
            c.close()
            # end boundary already covered poorly by date filter; explicitly query next day.
            c=db()
            extra=c.execute("""SELECT punch_time,punch_state FROM zk_attendance_raw
                               WHERE zk_user_id=(SELECT zk_user_id FROM employees WHERE emp_code=?)
                               AND punch_time>? AND punch_time<=? ORDER BY punch_time""",
                            (emp_code,start.isoformat(),end.isoformat())).fetchall(); c.close()
            times=[_parse_iso(r['punch_time']) for r in extra if _parse_iso(r['punch_time'])] or times
        cin=min(times); cout=max(times) if len(times)>1 else None
        late=0; early=0; overtime=0
        if start and cin>start+timedelta(minutes=grace):
            late=int((cin-start).total_seconds()//60)
        if end and cout:
            if cout<end: early=int((end-cout).total_seconds()//60)
            else: overtime=round((cout-end).total_seconds()/3600,2)
        hours=round((cout-cin).total_seconds()/3600,2) if cout else 0
        status='حاضر'
        c=db()
        leave=c.execute("""SELECT leave_type FROM leaves WHERE emp_code=? AND status IN ('موافق','approved','Approved') AND start_date<=? AND end_date>=? LIMIT 1""",(emp_code,work_date,work_date)).fetchone()
        c.close()
        if leave: status='إجازة'
        elif _holiday(work_date): status='عطلة'
        c=db()
        c.execute("""INSERT INTO attendance(work_date,emp_code,status,check_in,check_out,late_minutes,work_hours,overtime,notes)
                     VALUES(?,?,?,?,?,?,?,?,?)
                     ON CONFLICT(work_date,emp_code) DO UPDATE SET status=excluded.status,
                     check_in=excluded.check_in,check_out=excluded.check_out,late_minutes=excluded.late_minutes,
                     work_hours=excluded.work_hours,overtime=excluded.overtime,notes=excluded.notes""",
                  (work_date,emp_code,status,cin.isoformat(timespec='seconds'),
                   cout.isoformat(timespec='seconds') if cout else None,late,hours,overtime,
                   ('عطلة رسمية' if status=='عطلة' else (f'خروج مبكر {early} دقيقة' if early else ''))))
        c.commit(); c.close(); return True

    def process_all_pending(g,device_key=None):
        c=db()
        if device_key:
            rows=c.execute("""SELECT DISTINCT e.emp_code,date(r.punch_time) d FROM zk_attendance_raw r
                              JOIN employees e ON e.zk_user_id=r.zk_user_id
                              WHERE r.device_id=? AND r.match_status='matched'""",(device_key,)).fetchall()
        else:
            rows=c.execute("""SELECT DISTINCT e.emp_code,date(r.punch_time) d FROM zk_attendance_raw r
                              JOIN employees e ON e.zk_user_id=r.zk_user_id
                              WHERE r.match_status='matched'""").fetchall()
        c.close(); n=0
        for r in rows:
            try:
                if process_attendance_date(r['emp_code'],r['d']): n+=1
            except Exception: pass
        return {'processed':n}

    def _provision_user(adapter, device_key, emp, action='upsert'):
        conn=getattr(adapter,'_conn',None)
        if conn is None: adapter.connect(); conn=getattr(adapter,'_conn',None)
        if not conn or not hasattr(conn,'set_user'): raise RuntimeError('الجهاز/المكتبة لا يدعم إدارة المستخدمين')
        uid=str(emp['zk_user_id'] or emp['emp_code'])
        conn.set_user(uid=uid,name=str(emp['name'] or '')[:24],privilege=0,password='',group_id='',user_id=uid)
        return uid

    def provision_job(jid, device_ids, emp_codes, cancel_event=None, deadline=None):
        c=db(); emps=c.execute("SELECT emp_code,name,zk_user_id FROM employees WHERE emp_code IN (%s)" %
                              ','.join('?'*len(emp_codes)),emp_codes).fetchall() if emp_codes else []; c.close()
        job_update(jid,total=len(emps)*len(device_ids))
        for did in device_ids:
            if cancel_event and cancel_event.is_set(): return
            if deadline and time.time() >= float(deadline): return
            row=_device_row(did)
            if not row: continue
            adapter=None
            try:
                adapter=_adapter(row); adapter.connect()
                for emp in emps:
                    try:
                        _provision_user(adapter,row['device_key'],emp)
                        job_update(jid,done=job_get(jid)['done']+1,success=job_get(jid)['success']+1)
                    except Exception as e:
                        job_update(jid,done=job_get(jid)['done']+1,failed=job_get(jid)['failed']+1)
                        _job_item(jid,emp['emp_code'],'failed',str(e))
            except Exception as e:
                log_event(row['device_key'],'error','provision_failed',str(e))
            finally:
                try: adapter.disconnect()
                except Exception: pass

    def _job_item(jid,key,status,message):
        c=db(); c.execute("INSERT INTO zk_job_items(job_id,item_key,status,message,started_at,finished_at) VALUES(?,?,?,?,?,?)",
                          (jid,str(key),status,message,now(),now())); c.commit(); c.close()


    def set_device_time(device_id, cancel_event=None, deadline=None):
        row=_device_row(device_id)
        if not row: raise RuntimeError('الجهاز غير موجود')
        adapter=_adapter(row); adapter.connect()
        try:
            conn=getattr(adapter,'_conn',None)
            if not conn or not hasattr(conn,'set_time'):
                raise RuntimeError('هذا الموديل/البروتوكول لا يوفر ضبط وقت الجهاز عبر المكتبة الحالية')
            conn.set_time(datetime.now())
            _capture_device_info(adapter,row['device_key'],0)
            c=db(); c.execute("UPDATE zk_devices SET status='online',last_seen=?,updated_at=? WHERE device_key=?",(now(),now(),row['device_key'])); c.commit(); c.close()
            return True
        finally:
            try: adapter.disconnect()
            except Exception: pass

    def reconcile_device(device_id, cancel_event=None, deadline=None):
        row=_device_row(device_id)
        if not row: raise RuntimeError('الجهاز غير موجود')
        adapter=_adapter(row); adapter.connect(); conn=getattr(adapter,'_conn',None)
        users=[]
        try:
            if hasattr(conn,'get_users'): users=conn.get_users() or []
        finally:
            try: adapter.disconnect()
            except Exception: pass
        c=db()
        for u in users:
            uid=str(getattr(u,'uid',getattr(u,'user_id','')))
            name=str(getattr(u,'name','') or '')
            c.execute("""INSERT INTO zk_device_users(device_id,zk_user_id,name,privilege,enabled,first_seen,last_seen)
                         VALUES(?,?,?,?,?,?,?) ON CONFLICT(device_id,zk_user_id) DO UPDATE SET name=excluded.name,
                         privilege=excluded.privilege,last_seen=excluded.last_seen""",
                      (row['device_key'],uid,name,str(getattr(u,'privilege','')),1,now(),now()))
        c.commit(); c.close()
        return users

    def scheduler():
        while not _STOP.wait(60):
            try:
                c=db(); rows=c.execute("SELECT id,device_key FROM zk_devices WHERE active=1").fetchall(); c.close()
                for r in rows:
                    with _JOBS_LOCK:
                        running=any(v['kind']=='zkteco-sync' and v['status'] in ('queued','running')
                                   and v.get('device_id')==str(r['id']) for v in _JOBS.values())
                    if not running:
                        jid=start_job('zkteco-sync',_device_sync_job,r['id'],'scheduler',_owner='scheduler',_device_id=r['id'])
                        job_update(jid,device_id=str(r['id']))
            except Exception: pass

    global _SCHEDULER_STARTED
    if not _SCHEDULER_STARTED:
        _SCHEDULER_STARTED=True
        threading.Thread(target=scheduler,name='ZKTeco-Scheduler',daemon=True).start()

    def page_center(u,qs=''):
        c=db()
        devices=c.execute("""SELECT d.*,m.last_latency_ms,m.last_user_count,m.last_record_count,m.device_time,
                             m.server_time,m.time_drift_seconds,m.firmware,m.model,m.last_error
                             FROM zk_devices d LEFT JOIN zk_device_metrics m ON m.device_id=d.device_key
                             ORDER BY d.active DESC,d.name""").fetchall()
        unmatched=c.execute("SELECT COUNT(*) n FROM zk_unmatched WHERE status='open'").fetchone()['n']
        raw=c.execute("SELECT COUNT(*) n FROM zk_attendance_raw").fetchone()['n']
        c.close()
        trs=''
        for d in devices:
            st='🟢 Online' if d['status']=='online' else ('🔴 Offline' if d['status']=='offline' else '⚪ Unknown')
            drift=''
            if d['time_drift_seconds'] is not None:
                drift=f"{d['time_drift_seconds']:.0f}s"
            trs+=f"""<tr><td><b>{esc(d['name'] or d['device_key'])}</b><br><small>{esc(d['ip'])}:{d['port']}</small></td>
<td>{st}</td><td>{esc(d['last_seen'] or '—')}</td><td>{esc(d['last_sync_at'] or '—')}</td>
<td>{d['last_user_count'] or 0}</td><td>{d['last_record_count'] or 0}</td><td>{drift or '—'}</td>
<td><button class="btn" onclick="zkSync('{esc(str(d['id']))}')">🔄 Sync</button>
<button class="btn gray" onclick="zkRecon('{esc(str(d['id']))}')">👥 Reconcile</button>
<button class="btn gray" onclick="zkTime('{esc(str(d['id']))}')">🕒 ضبط الوقت</button></td></tr>"""
        body=f"""<div class="top"><div class="title"><h1>🖐 مركز أجهزة البصمة</h1>
<p>مراقبة ومزامنة ZKTeco بدون تعطيل الموقع. المزامنة تعمل في الخلفية تلقائياً كل دقيقة.</p></div>
<a class="btn gray" href="/zkteco/devices">⚙️ إعداد الأجهزة</a></div>
<div class="grid"><div class="card"><b>الأجهزة</b><h2>{len(devices)}</h2></div>
<div class="card"><b>غير المرتبطين</b><h2>{unmatched}</h2></div><div class="card"><b>Raw Punches</b><h2>{raw}</h2></div></div>
<div class="card table-wrap"><table class="table"><thead><tr><th>الجهاز</th><th>الحالة</th><th>آخر ظهور</th><th>آخر Sync</th><th>Users</th><th>Records</th><th>Time Drift</th><th>إجراءات</th></tr></thead><tbody>{trs or '<tr><td colspan=8>لم تتم إضافة أجهزة.</td></tr>'}</tbody></table></div>
<div class="toolbar" style="margin-top:14px">
<a class="btn gray" href="/zkteco/devices">⚙️ الأجهزة</a>
<a class="btn gray" href="/zkteco/attendance">📋 السجلات الخام</a>
<a class="btn gray" href="/zkteco/unmatched">🧩 غير المرتبطين</a>
</div>
<div class="card" style="margin-top:14px"><h3>👥 إدارة مستخدمي الأجهزة</h3>
<p>اربط الموظف برقم ZKTeco ثم أرسله للأجهزة. القوالب الحيوية (بصمة/وجه) لا يتم نقلها تلقائياً إلا إذا كان موديل الجهاز والبروتوكول يدعمان ذلك.</p>
<form onsubmit="return zkProvision(event)">
<input id="zkdevs" placeholder="Device IDs مفصولة بفاصلة">
<input id="zkemps" placeholder="Employee Codes مفصولة بفاصلة">
<button class="btn">⬆️ إرسال الموظفين للجهاز</button>
</form></div>
<div id="zkjob" class="card" style="display:none;margin-top:14px"><b id="zkjobmsg">جاري التنفيذ...</b><div style="margin-top:8px"><progress id="zkprog" max="100" value="0" style="width:100%"></progress></div><button class="btn bad" onclick="zkCancel(window.zkCurrentJob)">إلغاء</button></div>
<script>
async function zkRun(url,body){{let r=await fetch(url,{{method:'POST',headers:{{'Content-Type':'application/x-www-form-urlencoded'}},body:body+'&_csrf={esc(u.get("csrf",""))}'}});return await r.json()}}
async function zkSync(id){{let x=await zkRun('/zkteco/api/sync','id='+encodeURIComponent(id)); if(x.job) zkPoll(x.job); else alert(x.error||'تعذر بدء العملية')}}
async function zkCancel(id){{let x=await zkRun('/zkteco/api/cancel','id='+encodeURIComponent(id)); alert(x.message||x.error||'تم')}}
async function zkRecon(id){{let x=await zkRun('/zkteco/api/reconcile','id='+encodeURIComponent(id)); if(x.job) zkPoll(x.job); else alert(x.error||'تعذر بدء المطابقة');}}
async function zkTime(id){{let x=await zkRun('/zkteco/api/time','id='+encodeURIComponent(id)); if(x.job) zkPoll(x.job); else alert(x.error||'تعذر ضبط الوقت');}}
async function zkProvision(ev){{ev.preventDefault();let x=await zkRun('/zkteco/api/provision','device_ids='+encodeURIComponent(document.getElementById('zkdevs').value)+'&emp_codes='+encodeURIComponent(document.getElementById('zkemps').value));if(x.job)zkPoll(x.job);else alert(x.error||'تعذر بدء العملية');return false;}}
async function zkPoll(id){{window.zkCurrentJob=id;window.zkPollStarted=window.zkPollStarted||Date.now();if(Date.now()-window.zkPollStarted>1800000){{document.getElementById('zkjobmsg').textContent='انتهت مدة متابعة الصفحة. العملية قد تستمر على الخادم.';return;}}document.getElementById('zkjob').style.display='block';try{{let ctl=new AbortController();let timer=setTimeout(()=>ctl.abort(),8000);let r=await fetch('/zkteco/api/job?id='+encodeURIComponent(id),{{cache:'no-store',signal:ctl.signal}});clearTimeout(timer);if(!r.ok)throw new Error('HTTP '+r.status);let j=await r.json();document.getElementById('zkjobmsg').textContent=j.message||j.status;document.getElementById('zkprog').value=j.total?Math.round(j.done*100/j.total):0;if(j.status==='running'||j.status==='queued')setTimeout(()=>zkPoll(id),1000);else if(j.status==='success'){{window.zkPollStarted=0;setTimeout(()=>location.reload(),700);}}else if(j.status==='failed'||j.status==='cancelled'){{window.zkPollStarted=0;}}}}catch(e){{document.getElementById('zkjobmsg').textContent='تعذر تحديث الحالة مؤقتًا… سنحاول مرة أخرى.';setTimeout(()=>zkPoll(id),2000);}}}}
</script>"""
        return page_ref()('مركز أجهزة البصمة',body,u,'zkteco-center')

    old_get=H.do_GET; old_post=H.do_POST
    def get(self):
        p=self.path.split('?',1)[0]
        if p=='/zkteco/center':
            u=self.require()
            if not u:return None
            if not self.need(u,'system.manage'):return None
            return self.send(page_center(u,self.path.split('?',1)[1] if '?' in self.path else ''))
        if p=='/zkteco/api/job':
            u=self.require()
            if not u:return None
            jid=(self.path.split('id=',1)[1] if 'id=' in self.path else '')
            payload=json.dumps(job_get(jid),ensure_ascii=False).encode()
            self.send_response(200); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Length',str(len(payload))); self.end_headers(); self.wfile.write(payload); return None
        return old_get(self)
    def post(self):
        p=self.path.split('?',1)[0]
        if p not in ('/zkteco/api/sync','/zkteco/api/reconcile','/zkteco/api/provision','/zkteco/api/time','/zkteco/api/cancel'): return old_post(self)
        u=self.require()
        if not u:return None
        if not self.need(u,'system.manage'):return None
        f=self.form()
        if f.get('_csrf')!=u.get('csrf'):
            return self.send(page_ref()('خطأ أمني','<div class="alert">انتهت الجلسة. أعد المحاولة.</div>',u),403)
        try:
            if p=='/zkteco/api/cancel':
                jid=f.get('id',''); j=job_get(jid)
                if not j: payload={'error':'Job not found'}
                else:
                    with _CANCEL_LOCK:
                        ev=(g.get('_STABLE_JOB_EVENT')(jid) if g.get('_STABLE_JOB_EVENT') else _CANCEL_EVENTS.setdefault(jid,threading.Event()))
                        ev.set()
                    job_update(jid,cancel_requested=1,status='cancel_requested',message='جارٍ إيقاف العملية…')
                    payload={'message':'تم طلب إلغاء المزامنة'}
            elif p=='/zkteco/api/sync':
                did=f.get('id'); 
                with _JOBS_LOCK:
                    if any(v['kind']=='zkteco-sync' and v['status']=='running' for v in _JOBS.values()):
                        pass
                jid=start_job('zkteco-sync',_device_sync_job,did,u.get('username'),_owner=u.get('username'),_device_id=did)
                job_update(jid,device_id=str(did))
                payload={'job':jid}
            elif p=='/zkteco/api/reconcile':
                did=f.get('id'); jid=start_job('zkteco-reconcile',lambda _jid,device_id,**kw: reconcile_device(device_id),did,_owner=u.get('username'),_device_id=did); payload={'job':jid}
            elif p=='/zkteco/api/time':
                did=f.get('id'); jid=start_job('zkteco-time',lambda _jid,device_id,**kw: set_device_time(device_id),did,_owner=u.get('username'),_device_id=did); payload={'job':jid}
            else:
                ids=[x for x in f.get('device_ids','').split(',') if x]
                emps=[x for x in f.get('emp_codes','').split(',') if x]
                jid=start_job('zkteco-provision',lambda _jid,device_ids,emp_codes,**kw: provision_job(_jid,device_ids,emp_codes),ids,emps,_owner=u.get('username')); payload={'job':jid}
        except Exception as e: payload={'error':str(e)}
        b=json.dumps(payload,ensure_ascii=False).encode()
        self.send_response(200); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b); return None
    H.do_GET=get; H.do_POST=post

    old_page=g['page']
    def nav(title,body,user,active='dashboard'):
        out=old_page(title,body,user,active)
        if user and can(user,'system.manage'):
            out=out.replace('href="/zkteco/devices">🖐 أجهزة البصمة','href="/zkteco/center">🖐 أجهزة البصمة',1)
            out=out.replace('href="/zkteco/sync">🔄 مزامنة البصمة','href="/zkteco/center">🔄 مزامنة البصمة',1)
            out=out.replace('href="/zkteco/unmatched">🧩 غير مرتبطين (بصمة)','href="/zkteco/center">🧩 غير مرتبطين (بصمة)',1)
            out=out.replace('href="/zkteco/attendance">📋 سجلات حضور البصمة','href="/zkteco/center">📋 سجلات حضور البصمة',1)
        return out
    g['page']=nav

    g['zkteco_process_all_pending']=process_all_pending

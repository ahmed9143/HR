# HR Hospital - Final Stability & Simplification Layer
# Loaded LAST. Owns heavy/background operations, compact navigation, and safety guards.
import hashlib, sqlite3
import os, re, json, csv, io, threading, time, traceback, secrets, zipfile, hashlib, sqlite3
from urllib.parse import urlparse, quote, parse_qs


def install_stable_final(g):
    H=g['H']; db=g['db']; now=g['now']; can=g['can']; esc=g['esc']
    hr_log=g['hr_log']

    # ----------------------------------------------------------------------
    # COOPERATIVE CANCELLATION
    #
    # The watchdog used to only flip a job's *state* to 'timeout'. The worker
    # thread was still blocked inside `result = fn()`, so a large export kept
    # running — holding SQLite locks and RAM — long after the UI had reported
    # "انتهت مهلة الخادم". That mismatch is the real source of the "system is
    # stuck loading" symptom under load.
    #
    # JOB_CTX binds the running job id to the worker thread, so any long
    # operation can call job_should_stop() at a checkpoint and unwind cleanly.
    # ----------------------------------------------------------------------
    JOB_CTX=threading.local()

    def current_job_id():
        return getattr(JOB_CTX,'jid',None)

    def job_should_stop():
        """True when the current thread's job was cancelled or hit its deadline."""
        jid=current_job_id()
        if not jid: return False
        with JOB_LOCK:
            j=JOBS.get(jid)
        if not j: return False
        if j.get('cancel_requested'): return True
        if j.get('state') in ('cancelled','timeout','timed_out'): return True
        deadline=j.get('deadline')
        if deadline and time.time()>float(deadline): return True
        ev=JOB_CANCEL_EVENTS.get(jid)
        return bool(ev and ev.is_set())

    class JobCancelled(Exception):
        """Raised at a checkpoint so a long operation unwinds instead of finishing."""

    def job_checkpoint(progress=None,message=None):
        """Call this inside every loop of a heavy operation."""
        if job_should_stop():
            raise JobCancelled('تم إلغاء العملية أو انتهت مهلتها.')
        if progress is not None or message is not None:
            jid=current_job_id()
            if jid:
                kw={}
                if progress is not None: kw['done']=int(progress)
                if message is not None: kw['message']=message
                if kw: update(jid,**kw)

    # Published for layers loaded earlier (production_ops, zkteco_*), which look
    # these up lazily from globals at call time rather than at install time.
    g['job_should_stop']=job_should_stop
    g['job_checkpoint']=job_checkpoint
    g['JobCancelled']=JobCancelled
    g['current_job_id']=current_job_id
    original_page=g['_default_page']
    old_get=H.do_GET
    old_post=H.do_POST

    # ---- ONE background-job engine ----------------------------------------
    try:
        c=db(); c.execute('CREATE TABLE IF NOT EXISTS bulk_jobs(id TEXT PRIMARY KEY,kind TEXT,state TEXT,total INTEGER DEFAULT 0,done INTEGER DEFAULT 0,created INTEGER DEFAULT 0,owner TEXT,errors_json TEXT,result_path TEXT,started_at REAL,finished_at REAL,updated_at REAL,process_token TEXT)');
        cols={r['name'] for r in c.execute('PRAGMA table_info(bulk_jobs)').fetchall()}
        if 'process_token' not in cols: c.execute('ALTER TABLE bulk_jobs ADD COLUMN process_token TEXT')
        c.commit(); c.close()
    except sqlite3.Error as _e:
        g['hr_log']('job','silent_db_failure',level='WARNING',exc=_e,where='stable_final.py:74')
    # All heavy operations use this manager.  Legacy enterprise bulk-job
    # callbacks are rebound to the same engine below, so the project no longer
    # has two competing job stores.
    JOBS={}; JOB_LOCK=threading.RLock(); MAX_JOBS=250; MAX_ACTIVE_JOBS=8; JOB_TTL=24*3600
    JOB_DEFAULT_TIMEOUT=30*60
    JOB_QR_TIMEOUT=15*60
    JOB_ZK_TIMEOUT=20*60
    JOB_EXPORT_TIMEOUT=45*60
    JOB_CANCEL_EVENTS={}; JOB_THREADS={}; PROCESS_TOKEN=secrets.token_hex(8)
    PROCESS_HEARTBEAT_TTL=20
    try:
        c=db(); c.execute('CREATE TABLE IF NOT EXISTS job_processes(token TEXT PRIMARY KEY,started_at REAL NOT NULL,last_seen REAL NOT NULL)'); c.commit(); c.close()
        c=db(); c.execute('INSERT OR REPLACE INTO job_processes(token,started_at,last_seen) VALUES(?,?,?)',(PROCESS_TOKEN,time.time(),time.time())); c.commit(); c.close()
    except sqlite3.Error as _e:
        g['hr_log']('job','silent_db_failure',level='WARNING',exc=_e,where='stable_final.py:88')

    def _heartbeat_process():
        while True:
            try:
                c=db(); c.execute('PRAGMA busy_timeout=250'); c.execute('UPDATE job_processes SET last_seen=? WHERE token=?',(time.time(),PROCESS_TOKEN)); c.commit(); c.close()
            except sqlite3.Error as _e:
                g['hr_log']('job','silent_db_failure',level='WARNING',exc=_e,where='stable_final.py:94')
            time.sleep(5)
    threading.Thread(target=_heartbeat_process,daemon=True,name='HR-JobProcessHeartbeat').start()

    def _job_persist(j):
        c=None
        try:
            c=db()
            # Job telemetry is best-effort and must never hold an HTTP request
            # behind a business transaction. A short busy window is enough;
            # the in-memory state remains authoritative while the worker runs.
            try: c.execute('PRAGMA busy_timeout=250')
            except sqlite3.Error as e:
                hr_log('job','busy_timeout_pragma_failed',level='DEBUG',exc=e)
            c.execute("""INSERT INTO bulk_jobs(id,kind,state,total,done,created,owner,errors_json,result_path,started_at,finished_at,updated_at,process_token)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                         ON CONFLICT(id) DO UPDATE SET kind=excluded.kind,state=excluded.state,total=excluded.total,
                           done=excluded.done,created=excluded.created,errors_json=excluded.errors_json,
                           result_path=excluded.result_path,started_at=excluded.started_at,
                           finished_at=excluded.finished_at,updated_at=excluded.updated_at,process_token=excluded.process_token""",
                      (j['id'],j.get('kind','operation'),j.get('state',j.get('status','queued')),
                       int(j.get('total') or 0),int(j.get('done') or 0),int(j.get('created') or j.get('ok') or 0),
                       j.get('owner',j.get('user','')),json.dumps(j.get('errors',[])[-50:],ensure_ascii=False),
                       j.get('result_path'),j.get('started_at') or time.time(),j.get('finished_at'),time.time(),PROCESS_TOKEN))
            c.commit(); c.close()
        except sqlite3.Error as e:
            # Progress tracking must never break the actual business operation,
            # but a persistence failure means the in-memory job and the
            # bulk_jobs row have diverged: after a restart the job would look
            # stuck forever with no trace of why. Continue, but record it.
            hr_log('job','state_persist_failed',level='WARNING',exc=e,
                   job_id=j.get('id'),state=j.get('state'))
            try: c.close()
            except sqlite3.Error: pass

    def recover_stale_jobs():
        # Only recover jobs whose owning process has actually disappeared.
        # This avoids one live server process marking another live process's jobs as failed when multiple workers share the same SQLite DB.
        try:
            cutoff=time.time()-PROCESS_HEARTBEAT_TTL
            c=db(); c.execute('PRAGMA busy_timeout=500')
            rows=c.execute("SELECT DISTINCT process_token FROM bulk_jobs WHERE state IN ('queued','running','cancel_requested') AND process_token IS NOT NULL AND process_token<>?",(PROCESS_TOKEN,)).fetchall()
            stale=[]
            for r in rows:
                tok=r['process_token']
                h=c.execute('SELECT last_seen FROM job_processes WHERE token=?',(tok,)).fetchone()
                if not h or float(h['last_seen'] or 0)<cutoff: stale.append(tok)
            if stale:
                q=','.join('?' for _ in stale)
                c.execute(f"UPDATE bulk_jobs SET state='error', errors_json=?, finished_at=?, updated_at=? WHERE state IN ('queued','running','cancel_requested') AND process_token IN ({q})", [json.dumps([['system','عملية انقطعت بسبب توقف الخادم']],ensure_ascii=False),time.time(),time.time(),*stale])
            c.execute('DELETE FROM job_processes WHERE last_seen<?',(cutoff,))
            c.commit(); c.close()
        except Exception:
            try: c.close()
            except sqlite3.Error as _e:
                g['hr_log']('job','silent_db_failure',level='WARNING',exc=_e,where='stable_final.py:148')

    recover_stale_jobs()
    try:
        c=db()
        dup_rows=c.execute("SELECT kind,owner,MAX(created) AS keep_created FROM bulk_jobs WHERE state IN ('queued','running','cancel_requested') GROUP BY kind,owner HAVING COUNT(*)>1").fetchall()
        for d in dup_rows:
            c.execute("UPDATE bulk_jobs SET state='error',errors_json=?,finished_at=?,updated_at=? WHERE kind=? AND owner=? AND state IN ('queued','running','cancel_requested') AND created<?",(json.dumps([['system','تم إلغاء Job مكرر أثناء ترقية النظام']],ensure_ascii=False),time.time(),time.time(),d['kind'],d['owner'],d['keep_created']))
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_bulk_jobs_active_owner_kind ON bulk_jobs(kind,owner) WHERE state IN ('queued','running','cancel_requested')")
        c.commit(); c.close()
    except sqlite3.Error as _e:
        g['hr_log']('job','silent_db_failure',level='WARNING',exc=_e,where='stable_final.py:158')

    def cleanup_jobs():
        cutoff=time.time()-JOB_TTL
        with JOB_LOCK:
            old=[jid for jid,j in JOBS.items() if j.get('finished_at') and j['finished_at']<cutoff]
            for jid in old:
                JOBS.pop(jid,None); JOB_CANCEL_EVENTS.pop(jid,None); JOB_THREADS.pop(jid,None)
        try:
            c=db(); c.execute("DELETE FROM bulk_jobs WHERE finished_at IS NOT NULL AND finished_at<?",(cutoff,)); c.commit(); c.close()
        except sqlite3.Error as _e:
            g['hr_log']('job','silent_db_failure',level='WARNING',exc=_e,where='stable_final.py:168')

    def active_duplicate(kind,owner):
        with JOB_LOCK:
            for x in JOBS.values():
                if x.get('kind')==kind and x.get('owner','')==owner and x.get('state') in ('queued','running','cancel_requested'):
                    return x.get('id')
        try:
            c=db(); r=c.execute("SELECT id FROM bulk_jobs WHERE kind=? AND owner=? AND state IN ('queued','running','cancel_requested') ORDER BY created DESC LIMIT 1",(kind,owner)).fetchone(); c.close()
            return r['id'] if r else None
        except Exception: return None

    def new_job(kind,user=None,total=0,owner=None,timeout=None):
        cleanup_jobs()
        owner=owner if owner is not None else ((user or {}).get('username','') if isinstance(user,dict) else str(user or ''))
        duplicate=active_duplicate(kind,owner)
        if duplicate:
            return duplicate
        jid=secrets.token_urlsafe(10).replace('-','').replace('_','')[:14]
        started=time.time(); limit=float(timeout or JOB_DEFAULT_TIMEOUT)
        j={'id':jid,'kind':kind,'state':'queued','status':'queued','total':int(total or 0),'done':0,
           'ok':0,'success':0,'failed':0,'created':0,'errors':[],'started':started,'started_at':started,
           'finished':None,'finished_at':None,'result':None,'result_path':None,'owner':owner,'user':owner,
           'message':'','cancel_requested':False,'timeout':limit,'deadline':started+limit}
        with JOB_LOCK:
            active=sum(1 for x in JOBS.values() if x.get('state') in ('queued','running','cancel_requested'))
            if active >= MAX_ACTIVE_JOBS:
                raise RuntimeError('يوجد عدد كبير من العمليات قيد التنفيذ. حاول مرة أخرى بعد قليل.')
            JOBS[jid]=j; JOB_CANCEL_EVENTS[jid]=threading.Event()
            while len(JOBS)>MAX_JOBS:
                candidates=[x for x in JOBS.values() if x.get('finished_at')]
                victim=min(candidates or list(JOBS.values()),key=lambda x:x.get('started_at',0))
                if victim['id']==jid and len(JOBS)>1: break
                JOBS.pop(victim['id'],None); JOB_CANCEL_EVENTS.pop(victim['id'],None); JOB_THREADS.pop(victim['id'],None)
        try:
            c=db(); c.execute('PRAGMA busy_timeout=750'); c.execute('BEGIN IMMEDIATE')
            db_active=c.execute("SELECT COUNT(*) AS n FROM bulk_jobs WHERE state IN ('queued','running','cancel_requested')").fetchone()['n']
            if int(db_active or 0) >= MAX_ACTIVE_JOBS:
                c.rollback(); c.close(); raise RuntimeError('يوجد عدد كبير من العمليات قيد التنفيذ. حاول مرة أخرى بعد قليل.')
            dup=c.execute("SELECT id FROM bulk_jobs WHERE kind=? AND owner=? AND state IN ('queued','running','cancel_requested') ORDER BY created DESC LIMIT 1",(kind,owner)).fetchone()
            if dup:
                c.rollback(); c.close(); return dup['id']
            c.execute("INSERT INTO bulk_jobs(id,kind,state,total,done,created,owner,errors_json,result_path,started_at,finished_at,updated_at,process_token) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(jid,kind,'queued',int(total or 0),0,0,owner,'[]',None,started,None,started,PROCESS_TOKEN))
            c.commit(); c.close()
        except Exception as ex:
            try: c.close()
            except sqlite3.Error as _e:
                g['hr_log']('job','silent_db_failure',level='WARNING',exc=_e,where='stable_final.py:214')
            dup=active_duplicate(kind,owner)
            if dup: return dup
            raise RuntimeError('تعذر حجز العملية في قاعدة البيانات: '+str(ex))
        return jid

    def _event(jid):
        with JOB_LOCK: return JOB_CANCEL_EVENTS.setdefault(jid,threading.Event())

    def _cancelled(jid):
        with JOB_LOCK:
            j=JOBS.get(jid)
            return bool(_event(jid).is_set() or (j and (j.get('cancel_requested') or j.get('state') in ('cancelled','timeout','timed_out'))))

    def update(jid,**kw):
        with JOB_LOCK:
            j=JOBS.get(jid)
            if not j: return
            j.update(kw)
            if 'state' in kw: j['status']=kw['state']
            if 'status' in kw: j['state']=kw['status']
            j['updated_at']=time.time()
            if j.get('done') is not None: j['done']=int(j.get('done') or 0)
            j['ok']=int(j.get('ok',j.get('success',0)) or 0); j['success']=j['ok']
            j['failed']=int(j.get('failed',0) or 0)
            snapshot=dict(j)
            persist=('state' in kw or 'status' in kw or snapshot['done']==snapshot['total'] or snapshot['done']%25==0)
        if persist: _job_persist(snapshot)

    def finish_item(jid,ok=True,error=None,created=None):
        with JOB_LOCK:
            j=JOBS.get(jid)
            if not j:return
            if j.get('state') in ('cancelled','timeout','timed_out','done','error'):return
            j['done']=int(j.get('done',0))+1
            if ok:
                j['ok']=int(j.get('ok',0))+1; j['success']=j['ok']
                if created is not None:j['created']=int(j.get('created',0))+int(created or 0)
            else:
                j['failed']=int(j.get('failed',0))+1
                if error is not None and len(j['errors'])<100:j['errors'].append([str(error[0]),str(error[1])])
            snap=dict(j); persist=(j['done']%25==0 or j['done']>=j.get('total',0))
        if persist:_job_persist(snap)

    def get_job(jid,user):
        with JOB_LOCK: j=dict(JOBS.get(jid) or {})
        if not j:
            try:
                c=db(); r=c.execute('SELECT * FROM bulk_jobs WHERE id=?',(jid,)).fetchone(); c.close()
                if r:
                    j={'id':r['id'],'kind':r['kind'],'state':r['state'],'status':r['state'],'total':r['total'],'done':r['done'],
                       'created':r['created'],'ok':r['created'],'success':r['created'],'failed':0,
                       'owner':r['owner'],'user':r['owner'],'errors':json.loads(r['errors_json'] or '[]'),
                       'result_path':r['result_path'],'started_at':r['started_at'],'finished_at':r['finished_at'],'result':None}
            except Exception:return None
        if not j or j.get('owner',j.get('user',''))!=user.get('username',''):return None
        return j

    def _watchdog(jid):
        while True:
            with JOB_LOCK:
                j=JOBS.get(jid)
                if not j or j.get('state') not in ('queued','running'):return
                remaining=float(j.get('deadline',time.time()+1))-time.time()
            if remaining<=0:
                with JOB_LOCK:
                    j=JOBS.get(jid)
                    if j and j.get('state') in ('queued','running'):
                        j['cancel_requested']=True; j['state']=j['status']='timeout'; j['message']='انتهت مهلة الخادم للعملية'; j['finished']=j['finished_at']=time.time(); snap=dict(j)
                        _event(jid).set()
                _job_persist(snap); return
            time.sleep(min(1.0,remaining))

    def worker(jid,items,fn):
        update(jid,state='running',message='جاري التنفيذ')
        threading.Thread(target=_watchdog,args=(jid,),daemon=True,name='HR-JobWatch-'+jid).start()
        try:
            for item in items:
                if _cancelled(jid):break
                try:
                    if time.time() >= float(JOBS.get(jid,{}).get('deadline',time.time()+1)):
                        with JOB_LOCK: JOB_CANCEL_EVENTS[jid].set(); JOBS[jid]['cancel_requested']=True; JOBS[jid]['state']='timeout'; JOBS[jid]['finished_at']=time.time()
                        break
                    fn(item)
                    if _cancelled(jid):break
                    finish_item(jid,True)
                except Exception as ex: finish_item(jid,False,(item,ex))
        except Exception as ex: update(jid,message=str(ex))
        finally:
            with JOB_LOCK:j=JOBS.get(jid); state=j.get('state') if j else 'error'
            if j and state in ('running','queued'):
                update(jid,state='done',finished=time.time(),finished_at=time.time(),message='اكتملت العملية')
            elif j and state=='cancel_requested':
                update(jid,state='cancelled',finished=time.time(),finished_at=time.time(),message='تم إلغاء العملية')
            with JOB_LOCK: JOB_THREADS.pop(jid,None)

    RESULTS_DIR=os.path.join(g['DATA'],'job_results')

    def _persist_result(jid,result):
        """Write a large result to disk and return a lightweight descriptor.

        Job results used to live only in JOBS[jid]['result'] in RAM, so a 2 GB
        export sat in memory until the job was evicted, and a restart lost the
        finished export entirely while the DB still claimed the job succeeded.
        """
        payload=result[0] if isinstance(result,tuple) else result
        # Heavy operations now hand back a path to an archive already written to
        # disk; adopt it in place rather than reading it back into memory.
        if isinstance(payload,str) and payload and os.path.exists(payload):
            try:
                os.makedirs(RESULTS_DIR,exist_ok=True)
                final=os.path.join(RESULTS_DIR,f'{jid}.zip')
                if os.path.abspath(payload)!=os.path.abspath(final):
                    os.replace(payload,final)
                digest=hashlib.sha256()
                with open(final,'rb') as fh:
                    for block in iter(lambda:fh.read(1024*1024),b''): digest.update(block)
                return None,final,digest.hexdigest()
            except Exception as ex:
                g['log_error']('job-result-adopt',ex)
                return None,payload,None
        if not isinstance(payload,(bytes,bytearray)):
            return result,None,None
        try:
            os.makedirs(RESULTS_DIR,exist_ok=True)
            path=os.path.join(RESULTS_DIR,f'{jid}.zip')
            tmp=path+'.tmp'
            digest=hashlib.sha256()
            with open(tmp,'wb') as fh:
                fh.write(payload); digest.update(payload)
            os.replace(tmp,path)
            return None,path,digest.hexdigest()
        except Exception as ex:
            g['log_error']('job-result-persist',ex)
            return result,None,None

    def worker_one(jid,fn):
        update(jid,state='running',message='جاري التنفيذ')
        threading.Thread(target=_watchdog,args=(jid,),daemon=True,name='HR-JobWatch-'+jid).start()
        JOB_CTX.jid=jid
        try:
            result=fn()
            with JOB_LOCK:j=JOBS.get(jid); state=j.get('state') if j else 'error'
            if j and state=='running' and not _cancelled(jid):
                inline,path,checksum=_persist_result(jid,result)
                update(jid,state='done',finished=time.time(),finished_at=time.time(),done=1,ok=1,success=1,
                       result=inline,result_path=path,result_checksum=checksum,message='اكتملت العملية')
        except JobCancelled as ex:
            # Expected path: the operation noticed the cancel/deadline and
            # unwound at a checkpoint instead of running on invisibly.
            update(jid,state='cancelled',finished=time.time(),finished_at=time.time(),message=str(ex))
        except Exception as ex:
            with JOB_LOCK:j=JOBS.get(jid); state=j.get('state') if j else 'error'
            if j and state in ('running','queued'): update(jid,state='error',finished=time.time(),finished_at=time.time(),done=1,failed=1,errors=[['operation',str(ex)]],message=str(ex))
        finally:
            JOB_CTX.jid=None
            with JOB_LOCK: JOB_THREADS.pop(jid,None)

    def start_callable(u,kind,fn,total=1,timeout=None):
        jid=new_job(kind,u,total,timeout=timeout)
        th=threading.Thread(target=worker_one,args=(jid,fn),daemon=True,name='HR-'+re.sub(r'[^A-Za-z0-9]+','-',kind)[:30])
        with JOB_LOCK:JOB_THREADS[jid]=th
        th.start(); return jid

    def start_bulk_callable(u,kind,items,fn,timeout=None):
        jid=new_job(kind,u,len(items),timeout=timeout)
        th=threading.Thread(target=worker,args=(jid,items,fn),daemon=True,name='HR-'+re.sub(r'[^A-Za-z0-9]+','-',kind)[:30])
        with JOB_LOCK:JOB_THREADS[jid]=th
        th.start(); return jid

    def start_external_callable(kind, owner, target, args=(), kwargs=None, total=0, timeout=None):
        # Adapter for subsystems (ZKTeco, etc.) that need the same central job
        # state/event/timeout while retaining their own function signature.
        kwargs=dict(kwargs or {})
        jid=new_job(kind, {'username':str(owner or '')}, total, owner=str(owner or ''), timeout=timeout)
        def run():
            ev=_event(jid)
            update(jid,state='running',message='جاري التنفيذ')
            try:
                if _cancelled(jid): return
                target(jid,*tuple(args),cancel_event=ev,deadline=JOBS.get(jid,{}).get('deadline'),**kwargs)
                with JOB_LOCK: j=JOBS.get(jid); state=j.get('state') if j else 'error'
                if j and state in ('running','cancel_requested'):
                    if ev.is_set() or j.get('cancel_requested'):
                        update(jid,state='cancelled',finished=time.time(),finished_at=time.time(),message='تم إلغاء العملية')
                    else:
                        update(jid,state='done',finished=time.time(),finished_at=time.time(),message='اكتملت العملية')
            except Exception as ex:
                with JOB_LOCK: j=JOBS.get(jid); state=j.get('state') if j else 'error'
                if j and state in ('running','cancel_requested'):
                    update(jid,state='error',finished=time.time(),finished_at=time.time(),errors=[['operation',str(ex)]],message=str(ex))
            finally:
                with JOB_LOCK: JOB_THREADS.pop(jid,None)
        th=threading.Thread(target=run,daemon=True,name='HR-External-'+re.sub(r'[^A-Za-z0-9]+','-',kind)[:24])
        with JOB_LOCK: JOB_THREADS[jid]=th
        th.start(); return jid

    def cancel_job(jid,user):
        with JOB_LOCK:
            j=JOBS.get(jid)
            if not j:return False,'not_found'
            if j.get('owner')!=user.get('username','') and user.get('role') not in ('Admin','SuperAdmin'):return False,'forbidden'
            if j.get('state') not in ('queued','running'):return True,j.get('state')
            j['cancel_requested']=True; j['state']=j['status']='cancel_requested'; j['message']='جارٍ إيقاف العملية…'; snap=dict(j)
            _event(jid).set()
        _job_persist(snap); return True,'cancel_requested'

    def central_bulk_start(kind,total,fn,owner=''):
        # Compatibility API for enterprise_completion.py QR exports and legacy bulk pages.
        owner_user={'username':owner}
        jid=new_job(kind,owner_user,total,timeout=(JOB_EXPORT_TIMEOUT if 'export' in str(kind).lower() else JOB_DEFAULT_TIMEOUT))
        def run():
            update(jid,state='running')
            threading.Thread(target=_watchdog,args=(jid,),daemon=True).start()
            try:
                fn(jid)
                with JOB_LOCK:j=JOBS.get(jid); state=j.get('state') if j else 'error'
                if j and state=='running':update(jid,state='done',finished=time.time(),finished_at=time.time(),message='اكتملت العملية')
            except Exception as ex:
                update(jid,state='error',errors=[str(ex)],finished=time.time(),finished_at=time.time(),message=str(ex))
        th=threading.Thread(target=run,daemon=True,name='HR-Bulk-'+str(kind)[:24]);
        with JOB_LOCK:JOB_THREADS[jid]=th
        th.start(); return jid

    def central_bulk_get(jid):
        with JOB_LOCK:j=dict(JOBS.get(jid) or {})
        if j:return j
        try:
            c=db();r=c.execute('SELECT * FROM bulk_jobs WHERE id=?',(jid,)).fetchone();c.close()
            if not r:return None
            return {'id':r['id'],'kind':r['kind'],'state':r['state'],'status':r['state'],'total':r['total'],'done':r['done'],'created':r['created'],'owner':r['owner'],'errors':json.loads(r['errors_json'] or '[]'),'result_path':r['result_path']}
        except Exception:return None

    def central_bulk_update(jid,**kw): update(jid,**kw)
    def central_bulk_json(self,u,jid):
        j=central_bulk_get(jid)
        if not j:return None,404,{'ok':False,'error':'Job not found'}
        if j.get('owner') and j.get('owner')!=u.get('username') and u.get('role') not in ('Admin','SuperAdmin'):return None,403,{'ok':False,'error':'Forbidden'}
        return None,200,{'ok':True,'job':j}
    def stable_job_json(self,requester,u,jid):
        _,status,payload=central_bulk_json(u,jid)
        return requester.send(json.dumps(payload,ensure_ascii=False).encode(),status,'application/json',{'Cache-Control':'no-store'})
    H._job_json=stable_job_json

    # Rebind the legacy enterprise job API to this engine. Existing enterprise
    # handlers resolve these dictionary entries at runtime, so no second store remains.
    g['_bulk_job_start']=central_bulk_start; g['_bulk_job_get']=central_bulk_get; g['_bulk_job_update']=central_bulk_update; g['_bulk_job_json']=lambda u,jid: central_bulk_json(u,jid)
    g['_STABLE_JOB_CREATE']=lambda kind,owner=None,device_id=None,timeout=None: new_job(kind,{'username':owner or ''},0,owner=owner or '',timeout=timeout or (JOB_ZK_TIMEOUT if str(kind).startswith('zkteco') else JOB_DEFAULT_TIMEOUT))
    g['_STABLE_JOB_UPDATE']=update
    g['_STABLE_JOB_GET']=lambda jid: central_bulk_get(jid)
    g['_STABLE_JOB_EVENT']=_event
    g['_STABLE_JOB_CANCEL']=cancel_job
    g['_STABLE_JOB_EXTERNAL_START']=start_external_callable

    def find_callable(name):
        seen=set()
        def walk(obj,depth=0):
            if depth>12 or id(obj) in seen:return None
            seen.add(id(obj))
            if callable(obj) and getattr(obj,'__name__','')==name:return obj
            for cell in getattr(obj,'__closure__',()) or ():
                try:
                    found=walk(cell.cell_contents,depth+1)
                    if found:return found
                except Exception:pass
            return None
        for meth in (old_post,old_get):
            found=walk(meth)
            if found:return found
        return g.get(name)


    create_user=find_callable('create_user') if 'find_callable' in locals() else g.get('create_user')
    issue_qr=find_callable('issue_qr') if 'find_callable' in locals() else g.get('issue_qr')
    issue_qr_conn=find_callable('_issue_qr_conn') if 'find_callable' in locals() else g.get('_bulk_issue_qr_conn')
    export_package=find_callable('export_package') if 'find_callable' in locals() else g.get('export_package')
    bulk_provision=find_callable('bulk_provision') if 'find_callable' in locals() else g.get('bulk_provision')
    safe_name=g.get('safe_name',lambda x:str(x)); EMPFILES=g.get('EMPFILES',os.path.join(g.get('DATA',os.getcwd()),'employee_files'))

    def employee_items(kind,u):
        c=db()
        if kind=='users': rows=c.execute("SELECT e.emp_code FROM employees e WHERE e.status<>'مؤرشف' ORDER BY e.name").fetchall()
        else: rows=c.execute("SELECT e.emp_code FROM employees e WHERE e.status<>'مؤرشف' AND NOT EXISTS(SELECT 1 FROM qr_identities q WHERE q.emp_code=e.emp_code AND q.status='active') ORDER BY e.name").fetchall()
        c.close(); return [r['emp_code'] for r in rows if g['emp_allowed'](u,r['emp_code'])]

    qr_png=find_callable('qr_png') if 'find_callable' in locals() else g.get('qr_png')
    DATA=g.get('DATA',os.getcwd())

    def _qr_audit_batch(conn,user,rows):
        if not rows:return
        prev=conn.execute('SELECT hash FROM audit ORDER BY id DESC LIMIT 1').fetchone()
        prev_hash=prev['hash'] if prev and prev['hash'] else ''
        for action,emp,details in rows:
            ts=g['now'](); payload='|'.join([prev_hash,ts,str(user['username']),str(user['role']),str(action),'QR Identity',str(emp),str(details or ''),'','','',''])
            h=hashlib.sha256(payload.encode('utf-8')).hexdigest()
            conn.execute('INSERT INTO audit(ts,username,role,action,entity,record_key,details,prev_hash,hash,ip,before_json,after_json,reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(ts,user['username'],user['role'],action,'QR Identity',emp,details or '',prev_hash,h,'','','',''))
            prev_hash=h

    def _prepare_qr(emp,user,jid):
        if not qr_png: raise RuntimeError('QR generator unavailable')
        token=secrets.token_urlsafe(32)
        raw=qr_png(token)
        if raw is None: raise RuntimeError('QR generator returned no image')
        qdir=os.path.join(DATA,'qr'); os.makedirs(qdir,exist_ok=True)
        rel=os.path.join('qr',hashlib.sha256(str(emp).encode('utf-8')).hexdigest()[:24]+'.png').replace('\\','/')
        final_path=os.path.join(DATA,rel); tmp_path=final_path+'.tmp-'+jid
        with open(tmp_path,'wb') as fh: fh.write(raw)
        return token,rel,tmp_path,final_path

    def _run_qr_batch(jid,items,user,action='generate'):
        update(jid,state='running',message='جاري إنشاء رموز QR')
        threading.Thread(target=_watchdog,args=(jid,),daemon=True,name='HR-QR-Watch-'+jid).start()
        batch_size=25
        try:
            for start in range(0,len(items),batch_size):
                if _cancelled(jid):break
                batch=items[start:start+batch_size]; prepared=[]; audit_rows=[]; tmp_files=[]
                # IMPORTANT: no SQLite write transaction is held while QR images are
                # rendered. This was the hidden source of the browser-wide loading: a
                # bulk QR job held BEGIN IMMEDIATE while generating PNGs, blocking every
                # request that needed a SQLite write (including login/session updates).
                readc=db()
                try:
                    for emp in batch:
                        if _cancelled(jid):break
                        try:
                            row=readc.execute('SELECT emp_code,status,token_hash FROM qr_identities WHERE emp_code=?',(emp,)).fetchone()
                            emp_row=readc.execute('SELECT emp_code FROM employees WHERE emp_code=?',(emp,)).fetchone()
                            if not emp_row: raise ValueError('Employee not found')
                            was_active=bool(row and row['status']=='active')
                            if action!='regenerate' and action!='revoke' and was_active:
                                finish_item(jid,True); continue
                            if action=='revoke':
                                prepared.append(('revoke',emp,None,None,None,was_active)); continue
                            token,rel,tmp_path,final_path=_prepare_qr(emp,user,jid)
                            prepared.append(('upsert',emp,token,rel,final_path,was_active)); tmp_files.append(tmp_path)
                        except Exception as ex:
                            finish_item(jid,False,(emp,ex))
                finally:
                    readc.close()
                if not prepared:
                    for pth in tmp_files:
                        try: os.remove(pth)
                        except OSError: pass
                    continue
                conn=db()
                committed=False
                try:
                    conn.execute('BEGIN IMMEDIATE')
                    for typ,emp,token,rel,final_path,was_active in prepared:
                        if typ=='revoke':
                            cur=conn.execute('UPDATE qr_identities SET status="revoked",revoked_at=? WHERE emp_code=? AND status="active"',(g['now'](),emp))
                            if cur.rowcount: audit_rows.append(('QR_REVOKED',emp,'active -> revoked'))
                        else:
                            old=conn.execute('SELECT token_hash FROM qr_identities WHERE emp_code=?',(emp,)).fetchone()
                            old_token=old['token_hash'] if old else None
                            th=hashlib.sha256(token.encode()).hexdigest()
                            qr_cols={r['name'] for r in conn.execute('PRAGMA table_info(qr_identities)').fetchall()}
                            issued=g['now']()
                            if old:
                                if 'token' in qr_cols:
                                    # Legacy NOT NULL column: store a non-secret
                                    # marker, never the bearer token itself.
                                    conn.execute('UPDATE qr_identities SET token=?,token_hash=?,issued_at=?,revoked_at=NULL,status="active",created_by=?,regenerated_from=?,image_path=? WHERE emp_code=?',('redacted-'+th[:16],th,issued,user['username'],old_token,rel,emp))
                                else:
                                    conn.execute('UPDATE qr_identities SET token_hash=?,issued_at=?,revoked_at=NULL,status="active",created_by=?,regenerated_from=?,image_path=? WHERE emp_code=?',(th,issued,user['username'],old_token,rel,emp))
                            else:
                                if 'token' in qr_cols:
                                    conn.execute('INSERT INTO qr_identities(emp_code,token,token_hash,issued_at,status,created_by,regenerated_from,image_path) VALUES(?,?,?,?,?,?,?,?)',(emp,'redacted-'+th[:16],th,issued,'active',user['username'],None,rel))
                                else:
                                    conn.execute('INSERT INTO qr_identities(emp_code,token_hash,issued_at,status,created_by,regenerated_from,image_path) VALUES(?,?,?,?,?,?,?)',(emp,th,issued,'active',user['username'],None,rel))
                            audit_rows.append(('QR_REGENERATED' if was_active else 'QR_CREATED',emp,'active QR generated'))
                    _qr_audit_batch(conn,user,audit_rows)
                    conn.commit(); committed=True
                except Exception:
                    try: conn.rollback()
                    except sqlite3.Error as _e:
                        g['hr_log']('job','silent_db_failure',level='WARNING',exc=_e,where='stable_final.py:590')
                    raise
                finally:
                    conn.close()
                if committed:
                    for typ,emp,token,rel,final_path,was_active in prepared:
                        if typ=='upsert':
                            tmp_path=final_path+'.tmp-'+jid
                            try:
                                os.replace(tmp_path,final_path)
                            except OSError as move_err:
                                # The row is already committed as active, so a
                                # failed move would leave the database claiming
                                # a QR whose image does not exist and the job
                                # reporting success. Compensate: revoke the row,
                                # log it, and fail the item visibly.
                                hr_log('qr','image_move_failed',exc=move_err,
                                       emp_code=emp,job_id=jid,path=final_path)
                                try:
                                    cc=db()
                                    cc.execute("UPDATE qr_identities SET status='inconsistent',"
                                               "revoked_at=? WHERE emp_code=? AND status='active'",
                                               (g['now'](),emp))
                                    cc.commit(); cc.close()
                                except sqlite3.Error as comp_err:
                                    hr_log('qr','compensation_failed',exc=comp_err,emp_code=emp,job_id=jid)
                                try: os.remove(tmp_path)
                                except OSError: pass
                                finish_item(jid,False,error=(emp,f'تعذر حفظ صورة QR: {move_err}'))
                                continue
                            finish_item(jid,True)
                        elif typ=='revoke':
                            finish_item(jid,True)
                else:
                    for pth in tmp_files:
                        try:
                            os.remove(pth)
                        except OSError as rm_err:
                            hr_log('qr','temp_cleanup_failed',exc=rm_err,job_id=jid,path=pth)
                if _cancelled(jid):break
            with JOB_LOCK:j=JOBS.get(jid); state=j.get('state') if j else 'error'
            if j and state in ('running','queued'):
                update(jid,state='done',finished=time.time(),finished_at=time.time(),message='اكتملت عملية QR')
            elif j and state=='cancel_requested':
                update(jid,state='cancelled',finished=time.time(),finished_at=time.time(),message='تم إلغاء عملية QR')
        except Exception as ex:
            update(jid,state='error',finished=time.time(),finished_at=time.time(),message=str(ex),errors=[['QR batch',str(ex)]])
        finally:
            with JOB_LOCK:JOB_THREADS.pop(jid,None)

    def start_bulk(u,kind):
        if kind=='users':
            if not can(u,'users.manage'):return None,'forbid'
            fn=create_user
        else:
            if not can(u,'employees.edit'):return None,'forbid'
            fn=issue_qr
        if not fn:return None,'missing'
        items=employee_items(kind,u)
        if kind=='qr' and issue_qr_conn:
            jid=new_job('Bulk QR',u,len(items),timeout=JOB_QR_TIMEOUT)
            th=threading.Thread(target=_run_qr_batch,args=(jid,items,u,'generate'),daemon=True,name='HR-Bulk-QR')
            with JOB_LOCK:JOB_THREADS[jid]=th
            th.start(); return jid,None
        def one(emp): fn(emp,u) if kind=='users' else fn(emp,u,False)
        jid=new_job('Bulk Users' if kind=='users' else 'Bulk QR',u,len(items),timeout=JOB_QR_TIMEOUT if kind!='users' else JOB_DEFAULT_TIMEOUT)
        th=threading.Thread(target=worker,args=(jid,items,one),daemon=True,name='HR-Bulk-'+kind)
        with JOB_LOCK:JOB_THREADS[jid]=th
        th.start(); return jid,None

    def start_qr_bulk(u,ids,action='generate'):
        if not can(u,'employees.edit'):return None,'forbid'
        ids=[x.strip() for x in ids if x and x.strip()][:5000]; ids=[x for x in ids if g['emp_allowed'](u,x)]
        if action in ('generate','regenerate') and issue_qr_conn:
            jid=new_job('QR Bulk',u,len(ids),timeout=JOB_QR_TIMEOUT)
            th=threading.Thread(target=_run_qr_batch,args=(jid,ids,u,action),daemon=True,name='HR-Bulk-QR')
            with JOB_LOCK:JOB_THREADS[jid]=th
            th.start(); return jid,None
        def one(emp):
            if action=='revoke':
                c=db()
                try:
                    c.execute('UPDATE qr_identities SET status="revoked",revoked_at=? WHERE emp_code=? AND status="active"',(now(),emp)); c.commit()
                finally:c.close()
            else: issue_qr(emp,u,action=='regenerate')
        jid=new_job('QR Bulk',u,len(ids),timeout=JOB_QR_TIMEOUT)
        th=threading.Thread(target=worker,args=(jid,ids,one),daemon=True,name='HR-Bulk-QR')
        with JOB_LOCK:JOB_THREADS[jid]=th
        th.start(); return jid,None

    def start_export(u,include_credentials=False):
        if not can(u,'reports.export'):return None,'forbid'
        if not export_package:return None,'missing'
        return start_callable(u,'Full Export',lambda:export_package(u,include_credentials),1,JOB_EXPORT_TIMEOUT),None

    def start_provision(u):
        if not can(u,'users.manage'):return None,'forbid'
        if not bulk_provision:return None,'missing'
        return start_callable(u,'Full Employee Provisioning',lambda:bulk_provision(u),1,JOB_EXPORT_TIMEOUT),None

    def start_folders(u):
        if not can(u,'documents.bulk_import'):return None,'forbid'
        c=db();rows=c.execute("SELECT emp_code FROM employees WHERE status<>'مؤرشف' ORDER BY name").fetchall();c.close();rows=[r['emp_code'] for r in rows if g['emp_allowed'](u,r['emp_code'])]
        def one(emp):os.makedirs(os.path.join(EMPFILES,safe_name(emp)),exist_ok=True)
        jid=new_job('Employee Folders',u,len(rows),timeout=JOB_DEFAULT_TIMEOUT)
        th=threading.Thread(target=worker,args=(jid,rows,one),daemon=True,name='HR-Folders')
        with JOB_LOCK:JOB_THREADS[jid]=th
        th.start();return jid,None
    # ---- Compact primary navigation ---------------------------------------
    def hospital_page(title,body,user,active='dashboard'):
        # Build a clean 9-section sidebar from scratch. Legacy feature modules may still wrap page(),
        # but this final layer strips their duplicate links and leaves the useful routes accessible.
        if not user: return original_page(title,body,user,active)
        company=esc(g['setting']('company_name') or 'HR Hospital'); brand_tag=esc(g['setting']('brand_tagline') or 'نظام الموارد البشرية')
        groups=[]
        def add(label,items):
            items=[x for x in items if x]
            if items: groups.append((label,items))
        people=[]
        if can(user,'employees.view'): people.append(('employees','👥 الموظفون','/employees'))
        if user.get('role') in ('Manager','HR','Admin','SuperAdmin'): people.append(('requests','📥 طلبات الموظفين','/requests'))
        if user.get('role')=='Employee': people.append(('myhr','👤 حسابي الوظيفي','/myhr'))
        if user.get('role') in ('Manager','HR','Admin','SuperAdmin'): people.append(('hr-inbox','📥 مركز إجراءات HR','/hr-inbox'))
        if can(user,'employees.view'): people.append(('assets','📦 عهد الموظفين','/assets'))
        if can(user,'employees.edit'): people.append(('onboarding','🚀 تجهيز الموظفين','/employee/onboarding'))
        add('الموظفون',people)
        att=[]
        if can(user,'attendance.view'): att.append(('attendance','⏰ الحضور والانصراف','/attendance'))
        if can(user,'leave.create'): att.append(('leaves','🌴 الإجازات','/leaves'))
        if can(user,'leave.create'): att.append(('leave-balances','📊 أرصدة الإجازات','/leave-balances'))
        if can(user,'overtime.request'): att.append(('overtime','🕐 الإضافي','/overtime'))
        if can(user,'shifts.manage'): att.append(('shifts','🔁 الورديات','/shifts'))
        add('الحضور والإجازات',att)
        pay=[]
        if can(user,'payroll.view'): pay.append(('payroll','💰 المرتبات','/payroll'))
        if can(user,'payroll.view'): pay.append(('payroll-review','✅ مراجعة المرتبات','/payroll/review'))
        if can(user,'discipline.manage'): pay.append(('discipline','⚠️ الجزاءات','/discipline'))
        add('المرتبات',pay)
        docs=[]
        if can(user,'documents.manage'): docs.append(('documents','📄 المستندات','/documents'))
        add('المستندات',docs)
        qr=[]
        if can(user,'employees.view'): qr.append(('enterprise','🪪 البطاقات و QR','/enterprise'))
        add('البطاقات و QR',qr)
        reports=[]
        if can(user,'reports.view'): reports.append(('reports','📊 التقارير','/reports'))
        add('التقارير',reports)
        supplies=[]
        if can(user,'supplies.view'): supplies.append(('supplies','📦 المستلمات','/supplies'))
        add('المستلمات',supplies)
        imp=[]
        if can(user,'employees.edit'): imp.append(('import','📥 استيراد Excel','/import'))
        add('الاستيراد',imp)
        admin=[]
        if can(user,'roles.manage'): admin.append(('permissions','🔐 Permission Matrix','/permissions/matrix'))
        if can(user,'users.manage'): admin.append(('users','🔑 المستخدمون والصلاحيات','/users'))
        if can(user,'settings.manage'): admin.append(('settings','⚙️ الإعدادات','/settings'))
        if can(user,'system.manage'): admin.append(('zkteco-devices','🖐 أجهزة البصمة','/zkteco/devices'))
        if can(user,'backup.manage'): admin.append(('backups','💾 النسخ الاحتياطي','/backups'))
        if can(user,'settings.manage'): admin.append(('system','🛠 صحة النظام','/system'))
        if can(user,'audit.view'): admin.append(('audit','📜 سجل المراجعة','/audit'))
        add('الإدارة',admin)
        def gh(label,items):
            opened='open' if active in [x[0] for x in items] or label=='الموظفون' else ''
            return '<details class="nav-group" '+opened+'><summary>'+esc(label)+'</summary>'+''.join('<a class="'+('active' if active==k else '')+'" href="'+u+'">'+t+'</a>' for k,t,u in items)+'</details>'
        links='<a class="'+('active' if active=='dashboard' else '')+'" href="/">🏠 الرئيسية</a>'+''.join(gh(a,b) for a,b in groups)
        c=db(); n=c.execute('SELECT COUNT(*) n FROM notifications WHERE user_name=? AND read_at IS NULL',(user['username'],)).fetchone()['n']; c.close()
        links += f'<a href="/notifications">🔔 الإشعارات <span class="badge b-blue">{n}</span></a><a href="/password">🔐 تغيير كلمة المرور</a><a href="/logout">🚪 تسجيل الخروج</a>'
        search_box='''<div class="gsearch"><form action="/search" method="get"><input id="gsearch" name="q" placeholder="بحث سريع…" autocomplete="off"><kbd>Ctrl K</kbd></form><script>document.addEventListener('keydown',function(e){if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();var el=document.getElementById('gsearch');if(el){el.focus();el.select();}}});</script></div>'''
        forced='<div class="alert" style="margin-bottom:14px">🔐 يجب تغيير كلمة المرور قبل متابعة العمل. <a href="/password">تغيير الآن</a></div>' if user.get('must_change_password') else ''
        shell=f'''<!doctype html><html lang="ar"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" href="/branding/favicon"><title>{esc(title)} — {company}</title><link rel="stylesheet" href="/static/style.css?v={g['CSS_VERSION']}"></head><body><div class="app" id="appRoot"><button id="sideMobileToggle" class="mobile-menu" type="button">☰</button><div id="sideOverlay" class="side-overlay"></div><aside class="side" id="mainSide"><div class="brand"><button id="sideToggle" class="side-toggle" type="button">☰</button><div class="brand-info">{('<img src="/branding/logo" alt="logo" style="max-width:92px;max-height:58px;display:block;margin-bottom:10px;border-radius:10px;background:#fff;padding:5px">') if g['setting']('company_logo') else ''}<b>{company}</b><small>{brand_tag}</small></div></div>{search_box}<nav class="nav">{links}</nav><div class="footer">{esc(user['full_name'])} · {esc(user['role'])}</div></aside><main class="main">{forced}{body}<div class="footer">HR Hospital · نظام الموارد البشرية</div></main></div><script>{g['SIDE_JS']}</script><script>(function(){{let device=localStorage.getItem('hr_device_name');if(!device){{device=prompt('اسم هذا الجهاز داخل HR Hospital:',location.hostname)||('WEB-'+navigator.platform);localStorage.setItem('hr_device_name',device);}}async function hb(){{try{{await fetch('/device/ping?heartbeat='+Date.now(),{{headers:{{'X-HR-Device-Name':device}}}});}}catch(e){{}}}}hb();setInterval(hb,60000);}})();</script></body></html>'''
        # Same feature links as every other page (see server.extra_nav_links).
        return g['inject_extra_nav'](shell,user)

    # Own the shell for every module, not only the ones loaded after this one.
    # The curated navigation becomes the BASE the wrapper chain renders, while
    # page() keeps dispatching through the full chain, so every route ends up
    # with the same sidebar plus the same feature links.
    g['_SHELL_BASE']=hospital_page
    g['_PAGE_IMPL']=g['page']
    g['page']=g['_PAGE_IMPL']

    def job_html(u,j):
        data=json.dumps({k:v for k,v in j.items() if k!='result'},ensure_ascii=False)
        body=f'''<div class="top"><div class="title"><h1>⚙️ {esc(j.get('kind','عملية'))}</h1><p>العملية تعمل في الخلفية؛ يمكنك الانتقال لأي قسم بدون تجميد النظام.</p></div></div><div class="card" id="jobCard"><div id="jobStatus">جاري التجهيز…</div><div style="margin-top:14px;height:14px;background:#eef2f6;border-radius:99px;overflow:hidden"><div id="jobBar" style="width:0%;height:100%;background:#175cd3;transition:width .25s"></div></div><p id="jobMeta" style="color:#667085;margin-top:10px"></p><div id="jobErrors"></div><div class="actions" style="margin-top:16px"><a class="btn gray" href="/employees">الموظفون</a><a class="btn gray" href="/zkteco/devices">أجهزة البصمة</a><button class="btn bad" id="cancelJob" onclick="cancelJob()">إلغاء العملية</button></div></div><script>(function(){{var jid={json.dumps(j['id'])},fails=0,started=Date.now();function poll(){{if(Date.now()-started>1800000){{document.getElementById('jobStatus').textContent='انتهت مدة متابعة الصفحة. العملية قد تستمر على الخادم ويمكنك المتابعة لباقي النظام.';return;}}var ctl=new AbortController(),to=setTimeout(function(){{ctl.abort();}},8000);fetch('/employee/operations/job/'+encodeURIComponent(jid),{{cache:'no-store',signal:ctl.signal}}).then(function(r){{if(!r.ok)throw Error('HTTP '+r.status);return r.json()}}).then(function(j){{clearTimeout(to);fails=0;var total=j.total||1,done=j.done||0,p=Math.min(100,Math.round(done*100/total));document.getElementById('jobBar').style.width=p+'%';document.getElementById('jobStatus').textContent=j.status==='done'?(j.failed?'اكتملت العملية مع أخطاء':'اكتملت العملية بنجاح'):(j.status==='cancelled'||j.status==='cancel_requested'?'تم إلغاء العملية':(j.status==='timeout'||j.status==='timed_out'?'انتهت مهلة الخادم':(j.status==='error'?'فشلت العملية':'جاري التنفيذ…')));document.getElementById('jobMeta').textContent=(j.done||0)+' / '+(j.total||0)+' — ناجح: '+(j.ok||0)+' — فشل: '+(j.failed||0);if(j.errors&&j.errors.length){{var box=document.getElementById('jobErrors');box.textContent='';var wrap=document.createElement('div');wrap.className='alert';wrap.style.marginTop='14px';var hd=document.createElement('b');hd.textContent='الأخطاء:';wrap.appendChild(hd);j.errors.forEach(function(e){{wrap.appendChild(document.createElement('br'));var ln=document.createElement('span');ln.textContent=String(e[0])+' \u2014 '+String(e[1]);wrap.appendChild(ln);}});box.appendChild(wrap);}}if(!['done','error','cancelled','timeout','timed_out'].includes(j.status))setTimeout(poll,700);else if(j.result_available)document.getElementById('jobMeta').innerHTML+=' — <a href="/employee/operations/job/'+encodeURIComponent(jid)+'/download">تحميل النتيجة</a>';}}).catch(function(){{fails++;if(fails<40)setTimeout(poll,1500);else document.getElementById('jobStatus').textContent='تعذر تحديث الحالة مؤقتًا — العملية مستمرة على الخادم.';}})}}function cancelJob(){{fetch('/employee/operations/job/'+encodeURIComponent(jid)+'/cancel',{{method:'POST',headers:{{'Content-Type':'application/x-www-form-urlencoded'}},body:'_csrf='+encodeURIComponent({json.dumps(u.get('csrf',''))})}}).catch(function(){{}});document.getElementById('jobStatus').textContent='جارٍ إلغاء العملية…';}}poll()}})();</script>'''
        return hospital_page('عملية في الخلفية',body,u,'employees')

    def get(self):
        p=urlparse(self.path).path
        if p.startswith('/employee/operations/job/'):
            u=self.require()
            if not u:return None
            tail=p.split('/employee/operations/job/',1)[1]
            if tail.endswith('/download'):
                jid=tail[:-9].rstrip('/'); j=get_job(jid,u)
                if not j:return self.send(b'Not found',404,'text/plain')
                # Prefer the on-disk copy: it survives a restart and is not held
                # in RAM for the lifetime of the job record.
                rp=j.get('result_path')
                if rp and os.path.exists(rp):
                    with open(rp,'rb') as fh: data=fh.read()
                    return self.send(data,200,'application/zip',{'Content-Disposition':'attachment; filename="HR_Operation_Result.zip"','Cache-Control':'no-store'})
                result=j.get('result')
                if result is None:return self.send(b'Not ready',409,'text/plain')
                # bulk_provision returns (zip_bytes,count,errors)
                if isinstance(result,tuple): data=result[0]
                else: data=result
                return self.send(data,200,'application/zip',{'Content-Disposition':'attachment; filename="HR_Operation_Result.zip"','Cache-Control':'no-store'})
            jid=tail; j=get_job(jid,u)
            if not j:return self.send(json.dumps({'error':'not found'}),404,'application/json')
            payload={k:v for k,v in j.items() if k!='result'}
            payload['result_available']=(j.get('result') is not None) or bool(j.get('result_path') and os.path.exists(j.get('result_path')))
            return self.send(json.dumps(payload,ensure_ascii=False),200,'application/json; charset=utf-8',{'Cache-Control':'no-store'})
        if p.startswith('/employee/operations/jobs/'):
            u=self.require()
            if not u:return None
            jid=p.rsplit('/',1)[-1]; j=get_job(jid,u)
            if not j:return self.send(hospital_page('غير موجود','<div class="card"><div class="alert">العملية غير موجودة أو انتهت صلاحيتها.</div></div>',u),404)
            return self.send(job_html(u,j))
        # Legacy GET endpoints used to perform writes/heavy exports inline.
        # GET is now navigation-only; the corresponding POST buttons launch jobs.
        if p in ('/employee/operations/folders','/employee/operations/export'):
            u=self.require()
            if not u:return None
            return self.redirect('/employee/operations')
        if p=='/employee/operations':
            u=self.require()
            if not u:return None
            if not can(u,'employees.view'): return self.forbid(u)
            c=db(); total=c.execute("SELECT COUNT(*) n FROM employees WHERE status<>'مؤرشف'").fetchone()['n']; noqr=c.execute("SELECT COUNT(*) n FROM employees e WHERE e.status<>'مؤرشف' AND NOT EXISTS(SELECT 1 FROM qr_identities q WHERE q.emp_code=e.emp_code AND q.status='active')").fetchone()['n']; nouser=c.execute("SELECT COUNT(*) n FROM employees e WHERE e.status<>'مؤرشف' AND NOT EXISTS(SELECT 1 FROM users u WHERE u.employee_code=e.emp_code AND u.active=1)").fetchone()['n']; c.close()
            body=f'''<div class="top"><div class="title"><h1>⚡ عمليات الموظفين</h1><p>عمليات جماعية آمنة تعمل في الخلفية ولا توقف النظام.</p></div></div><div class="grid g3"><div class="card metric"><div class="label">الموظفون</div><div class="value">{total}</div></div><div class="card metric"><div class="label">بدون QR</div><div class="value">{noqr}</div></div><div class="card metric"><div class="label">بدون User</div><div class="value">{nouser}</div></div></div><div class="grid g2" style="margin-top:16px"><div class="card"><h3>🔐 الحسابات</h3><p>إنشاء User لكل موظف بدون حساب.</p><form method="post" action="/employee/operations/users">{g['csrf_field'](u)}<button class="btn">إنشاء Users في الخلفية</button></form></div><div class="card"><h3>🔳 QR</h3><p>إنشاء QR للموظفين الذين لا يملكون QR نشط.</p><form method="post" action="/employee/operations/qr">{g['csrf_field'](u)}<button class="btn">إنشاء QR في الخلفية</button></form></div><div class="card"><h3>⚡ تجهيز شامل</h3><p>User + QR + Folder + ملف نتيجة.</p><form method="post" action="/employee/operations/provision">{g['csrf_field'](u)}<button class="btn">تشغيل التجهيز الشامل</button></form></div><div class="card"><h3>📦 Export</h3><p>تصدير بيانات الموظفين والمستندات والـ QR.</p><form method="post" action="/employee/operations/export">{g['csrf_field'](u)}<button class="btn gray">بدء التصدير</button></form></div><div class="card"><h3>📁 المجلدات</h3><p>إنشاء مجلد مستقل لكل موظف.</p><form method="post" action="/employee/operations/folders">{g['csrf_field'](u)}<button class="btn gray">إنشاء المجلدات</button></form></div></div>'''
            return self.send(hospital_page('عمليات الموظفين',body,u,'employees'))
        return old_get(self)

    def post(self):
        p=urlparse(self.path).path
        u=None
        if p in ('/employee/operations/users','/employee/operations/qr','/employee/operations/provision','/employee/operations/export','/employee/operations/folders','/qr/generate-all','/qr/bulk','/qr/generate','/qr/regenerate'):
            u=self.require()
            if not u:return None
            f=H.form(self)
            if f.get('_csrf')!=u.get('csrf'): return self.send(hospital_page('Security','<div class="card"><div class="alert">Invalid CSRF.</div></div>',u),403)
        if p in ('/employee/operations/users','/employee/operations/qr'):
            if u.get('must_change_password'): return self.redirect('/password')
            kind='users' if p.endswith('/users') else 'qr'; jid,err=start_bulk(u,kind)
            if err=='forbid': return self.forbid(u)
            if err: return self.send(hospital_page('Bulk Error','<div class="card"><div class="alert">محرك العملية غير متاح.</div></div>',u),500)
            return self.redirect('/employee/operations/jobs/'+quote(jid))
        if p=='/employee/operations/provision':
            jid,err=start_provision(u)
            if err=='forbid': return self.forbid(u)
            if err: return self.send(hospital_page('Provisioning Error','<div class="card"><div class="alert">محرك التجهيز غير متاح.</div></div>',u),500)
            return self.redirect('/employee/operations/jobs/'+quote(jid))
        if p=='/employee/operations/export':
            jid,err=start_export(u,False)
            if err=='forbid': return self.forbid(u)
            if err: return self.send(hospital_page('Export Error','<div class="card"><div class="alert">محرك التصدير غير متاح.</div></div>',u),500)
            return self.redirect('/employee/operations/jobs/'+quote(jid))
        if p=='/employee/operations/folders':
            jid,err=start_folders(u)
            if err=='forbid': return self.forbid(u)
            if err: return self.send(hospital_page('Folders Error','<div class="card"><div class="alert">محرك المجلدات غير متاح.</div></div>',u),500)
            return self.redirect('/employee/operations/jobs/'+quote(jid))
        if p in ('/qr/generate-all','/qr/bulk'):
            # SINGLE SOURCE OF TRUTH for bulk QR authorization. This module wins
            # the route at runtime; the contradictory is_admin guard that used
            # to sit in v13_security_ux was dead code and has been removed.
            # 'employees.edit' was an implicit proxy — a store-wide badge
            # operation now has its own explicitly grantable permission.
            if not can(u,'qr.bulk_generate'): return self.forbid(u)
            if p=='/qr/generate-all':
                ids=employee_items('qr',u); action='generate'
            else:
                ids=f.get('emp_codes','').split(','); action=f.get('action','generate')
            ids=[x.strip() for x in ids if x and x.strip()][:5000]
            ids=[x for x in ids if g['emp_allowed'](u,x)]
            jid,err=start_qr_bulk(u,ids,action)
            if err=='forbid': return self.forbid(u)
            if err: return self.send(hospital_page('QR Error','<div class="card"><div class="alert">محرك QR غير متاح.</div></div>',u),500)
            return self.redirect('/employee/operations/jobs/'+quote(jid))
        if p in ('/qr/generate','/qr/regenerate'):
            # Individual QR is always a background job: the HTTP request must never
            # wait for QR generation, PNG I/O, SQLite locks, or audit writes.
            if u.get('must_change_password'): return self.redirect('/password')
            # Same permission as the bulk route. Issuing or re-issuing a single
            # badge is the same capability as issuing all of them, so it must be
            # the same grant — 'employees.edit' was an unrelated proxy, and
            # having the two QR routes on different permissions is exactly the
            # kind of split that hid the earlier token defect.
            if not can(u,'qr.bulk_generate'): return self.forbid(u)
            emp=f.get('emp_code','').strip()
            if not emp or not g['emp_allowed'](u,emp): return self.forbid(u)
            jid,err=start_qr_bulk(u,[emp],'regenerate' if p=='/qr/regenerate' else 'generate')
            if err=='forbid': return self.forbid(u)
            if err: return self.send(hospital_page('QR Error','<div class="card"><div class="alert">تعذر بدء عملية QR.</div></div>',u),500)
            return self.redirect('/employee/operations/jobs/'+quote(jid))
        if p.startswith('/employee/operations/job/') and p.endswith('/cancel'):
            u=self.require()
            if not u:return None
            jid=p.split('/employee/operations/job/',1)[1][:-7].rstrip('/')
            ok,msg=cancel_job(jid,u)
            if not ok:return self.send(json.dumps({'ok':False,'error':msg}),403 if msg=='forbidden' else 404,'application/json')
            return self.send(json.dumps({'ok':True,'status':msg}),200,'application/json')
        if p=='/bulk/jobs/cancel':
            u=self.require()
            if not u:return None
            f=self.form()
            if f.get('_csrf')!=u.get('csrf'):return self.send(json.dumps({'ok':False,'error':'CSRF'}),403,'application/json')
            ok,msg=cancel_job(f.get('id',''),u)
            if not ok:return self.send(json.dumps({'ok':False,'error':msg}),403 if msg=='forbidden' else 404,'application/json')
            return self.send(json.dumps({'ok':True,'status':msg}),200,'application/json')
        return old_post(self)

    H.do_GET=get; H.do_POST=post
    return ''

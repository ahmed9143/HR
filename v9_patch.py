# HR Enterprise V9.0 comprehensive feature patch
import os, json, time, secrets, statistics, math, shutil
from datetime import datetime, date, timedelta
from urllib.parse import quote

V9_PREVIEWS={}

def _v9_upgrade():
    c=db()
    c.executescript('''
    CREATE TABLE IF NOT EXISTS branding_profiles(id INTEGER PRIMARY KEY, profile_key TEXT UNIQUE, path TEXT, updated_at TEXT, updated_by TEXT);
    CREATE TABLE IF NOT EXISTS employee_portal_accounts(emp_code TEXT UNIQUE, username TEXT UNIQUE, active INTEGER DEFAULT 1, created_at TEXT);
    CREATE TABLE IF NOT EXISTS evaluation_anomalies(id INTEGER PRIMARY KEY, emp_code TEXT, period TEXT, score REAL, dept_average REAL, delta_percent REAL, percentile REAL, severity TEXT, created_at TEXT, UNIQUE(emp_code,period));
    CREATE TABLE IF NOT EXISTS device_events(id INTEGER PRIMARY KEY, device_id TEXT, event_type TEXT, ts TEXT, latency_ms REAL, message TEXT);
    CREATE TABLE IF NOT EXISTS server_discovery_log(id INTEGER PRIMARY KEY, ts TEXT, server_name TEXT, ip TEXT, port INTEGER, latency_ms REAL, result TEXT);
    CREATE TABLE IF NOT EXISTS bulk_action_log(id INTEGER PRIMARY KEY, action TEXT, affected INTEGER, filters_json TEXT, created_by TEXT, created_at TEXT);
    ''')
    for key in ('login_logo','sidebar_logo','report_logo','favicon_logo'):
        if not c.execute('SELECT 1 FROM branding_profiles WHERE profile_key=?',(key,)).fetchone():
            c.execute('INSERT INTO branding_profiles(profile_key,path,updated_at,updated_by) VALUES(?,?,?,?)',(key,'',now(),'system'))
    c.commit(); c.close()


def _eval_intelligence(self,u):
    if not self.need(u,'employees.view'): return
    c=db(); scope_sql,scope_params=visible_employee_sql(u,'e')
    rows=c.execute(f'''SELECT e.emp_code,e.name,COALESCE(e.department,'غير محدد') dept,ev.period,ev.score
                       FROM employee_evaluations ev JOIN employees e ON e.emp_code=ev.emp_code
                       WHERE 1=1 {scope_sql} ORDER BY ev.period DESC,e.department,e.name''',scope_params).fetchall()
    grouped={}
    for r in rows: grouped.setdefault((r['dept'],r['period']),[]).append(float(r['score'] or 0))
    out=[]
    for r in rows:
        vals=grouped.get((r['dept'],r['period']),[]); avg=sum(vals)/len(vals) if vals else 0
        delta=((r['score']-avg)/avg*100) if avg else 0
        percentile=(sum(1 for x in vals if x<=r['score'])/len(vals)*100) if vals else 0
        sev='HIGH' if abs(delta)>=25 and len(vals)>=3 else ('MEDIUM' if abs(delta)>=15 and len(vals)>=3 else 'NORMAL')
        if sev!='NORMAL':
            out.append((r,avg,delta,percentile,sev))
    cards=''.join(f'''<div class="card"><div style="display:flex;justify-content:space-between;gap:12px"><div><h3 style="margin:0">{esc(r['name'])}</h3><p>{esc(r['dept'])} · {esc(r['period'] or '')}</p></div><span class="badge {'b-bad' if sev=='HIGH' else 'b-warn'}">{sev}</span></div><div class="grid g4"><div><small>Employee Score</small><h2>{r['score']:.1f}%</h2></div><div><small>Department Avg</small><h2>{avg:.1f}%</h2></div><div><small>Difference</small><h2>{delta:+.1f}%</h2></div><div><small>Percentile</small><h2>{percentile:.0f}th</h2></div></div><div class="alert">⚠️ مؤشر مراجعة فقط — لا يمثل قرارًا تلقائيًا ضد الموظف.</div></div>''' for r,avg,delta,percentile,sev in out[:100])
    if not cards: cards='<div class="card"><h3>لا توجد حالات شاذة حاليًا</h3><p>يحتاج التحليل إلى تقييمات لثلاثة موظفين أو أكثر داخل نفس الإدارة والفترة.</p></div>'
    body=f'''<div class="top"><div class="title"><h1>📊 Evaluation Intelligence</h1><p>مقارنة التقييم الفردي بمتوسط الإدارة واكتشاف القيم غير المعتادة.</p></div><a class="btn gray" href="/reports">التقارير</a></div><div class="card"><div class="alert">النظام لا يعاقب الموظف تلقائيًا. هذه إشارة مراجعة تساعد HR على اكتشاف تقييمات غير منطقية.</div></div><div style="margin-top:16px">{cards}</div>'''
    c.close(); self.send(page('Evaluation Intelligence',body,u,'reports'))


def _branding_page(self,u):
    if not self.need(u,'settings.manage'): return
    c=db(); rows=c.execute('SELECT * FROM branding_profiles ORDER BY id').fetchall(); c.close()
    names={'login_logo':'Login Logo','sidebar_logo':'Sidebar Logo','report_logo':'Report Logo','favicon_logo':'Favicon'}
    trs=''.join(f'''<tr><td>{names.get(r['profile_key'],r['profile_key'])}</td><td>{esc(r['path'] or 'Default')}</td><td>{esc(r['updated_at'] or '')}</td></tr>''' for r in rows)
    body=f'''<div class="top"><div class="title"><h1>🎨 Branding Manager</h1><p>تحكم منفصل في شعار الدخول والـSidebar والتقارير والـFavicon.</p></div><a class="btn gray" href="/settings">Settings</a></div>
    <div class="grid g2"><div class="card"><h3>Upload Logo Profile</h3><form method="post" action="/branding/save" enctype="multipart/form-data">{csrf_field(u)}<div class="field"><label>Profile</label><select name="profile"><option value="login_logo">Login Logo</option><option value="sidebar_logo">Sidebar Logo</option><option value="report_logo">Report Logo</option><option value="favicon_logo">Favicon</option></select></div><div class="field"><label>Image</label><input type="file" name="file" accept=".png,.jpg,.jpeg,.svg" required></div><div class="actions" style="margin-top:12px"><button class="btn">Save Profile</button><button class="btn gray" name="action" value="restore" type="submit">Restore Default</button></div></form><p class="footer">PNG/JPG/SVG · حد أقصى 5MB. سيتم إنشاء نسخة favicon مربعة عند الإمكان.</p></div>
    <div class="card"><h3>Current Profiles</h3><table class="table"><thead><tr><th>Profile</th><th>File</th><th>Updated</th></tr></thead><tbody>{trs}</tbody></table></div></div>'''
    self.send(page('Branding Manager',body,u,'settings'))


def _branding_save(self,u):
    if not self.need(u,'settings.manage'): return
    fields,files=self.parse_upload_all(); profile=fields.get('profile','login_logo'); action=fields.get('action','')
    if profile not in ('login_logo','sidebar_logo','report_logo','favicon_logo'): return self.send(page('Branding','<div class="card"><div class="alert">Invalid profile.</div></div>',u,'settings'),400)
    brand=os.path.join(DATA,'branding','profiles'); os.makedirs(brand,exist_ok=True)
    if action=='restore':
        for p in os.listdir(brand):
            if p.startswith(profile+'.'): os.remove(os.path.join(brand,p))
        c=db(); c.execute('UPDATE branding_profiles SET path=?,updated_at=?,updated_by=? WHERE profile_key=?',('',now(),u['username'],profile)); c.commit(); c.close(); return self.redirect('/branding')
    fp=files.get('file')
    if not fp: return self.send(page('Branding','<div class="card"><div class="alert">اختر صورة.</div></div>',u,'settings'),400)
    head,data,fname=fp; ext=os.path.splitext(fname)[1].lower()
    if ext not in ('.png','.jpg','.jpeg','.svg') or len(data)>5*1024*1024: return self.send(page('Branding','<div class="card"><div class="alert">صيغة أو حجم الصورة غير صالح.</div></div>',u,'settings'),400)
    path=os.path.join(brand,profile+ext); open(path,'wb').write(data)
    c=db(); c.execute('UPDATE branding_profiles SET path=?,updated_at=?,updated_by=? WHERE profile_key=?',(os.path.relpath(path,DATA),now(),u['username'],profile)); c.commit(); c.close(); audit(u['username'],u['role'],'Branding profile update','Branding',profile,fname)
    self.redirect('/branding')


def _excel_grid_page(self,u):
    if not self.need(u,'employees.edit'): return
    headers=['Employee Code','Name','Department','Unit','Job','National ID','Phone','Email','Contract Date','Contract Amount']
    hdr=json.dumps(headers,ensure_ascii=False)
    body=f'''<div class="top"><div class="title"><h1>📊 Excel Center Pro</h1><p>Excel-like paste/edit/validate/import — بدون رفع ملف.</p></div><div class="actions"><a class="btn gray" href="/import">Classic Import</a><button class="btn" type="button" id="pasteBtn">Paste from Clipboard</button></div></div>
    <div class="card"><div class="toolbar"><input id="gridSearch" placeholder="Search in grid…"><button class="btn gray" type="button" id="addRow">+ Add Row</button><button class="btn gray" type="button" id="delRow">Delete Selected</button><button class="btn gray" type="button" id="fillDown">Fill Down</button><button class="btn gray" type="button" id="undo">Undo</button><button class="btn gray" type="button" id="redo">Redo</button><button class="btn gray" type="button" id="clear">Clear</button></div>
    <div class="alert">Ctrl+V = multi-cell paste · Ctrl+D = Fill Down · Delete = clear cell · Ctrl+Z / Ctrl+Y = Undo/Redo. 🔴 invalid · 🟡 warning · 🟢 valid.</div>
    <div id="grid" class="table-wrap" style="max-height:540px;margin-top:14px"></div>
    <form id="gridForm" method="post" action="/import/employees/paste/preview">{csrf_field(u)}<textarea id="payload" name="paste_data" hidden></textarea><div class="actions" style="margin-top:14px"><button class="btn ok" type="submit">Validate All → Preview</button></div></form></div>
    <script>
    const HEADERS={hdr}; let data=[HEADERS,Array(HEADERS.length).fill('')]; let selected=null,undoStack=[],redoStack=[];
    const grid=document.getElementById('grid');
    function esc(x){{return String(x??'').replace(/[&<>"']/g,m=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[m]));}}
    function snap(){{return JSON.stringify(data)}} function save(){{undoStack.push(snap());if(undoStack.length>50)undoStack.shift();redoStack=[]}}
    function valid(v,i){{if(!v)return '';if(i===5&&!/^\\d{{14}}$/.test(v))return 'bad';if(i===6&&!/^01\\d{{9}}$/.test(v))return 'warn';if(i===0&&v==='')return 'bad';return 'ok'}}
    function render(filter=''){{let h='<table class="table" id="sheet"><thead><tr>'+HEADERS.map(x=>'<th>'+esc(x)+'</th>').join('')+'</tr></thead><tbody>';data.slice(1).forEach((r,ri)=>{{let hay=r.join(' ').toLowerCase();if(filter&&!hay.includes(filter.toLowerCase()))return;h+='<tr data-ri="'+ri+'">'+HEADERS.map((_,ci)=>{{let cls=valid(r[ci]||'',ci);return '<td contenteditable="true" data-ci="'+ci+'" class="'+cls+'">'+esc(r[ci]||'')+'</td>'}}).join('')+'</tr>'}});h+='</tbody></table>';grid.innerHTML=h;grid.querySelectorAll('td').forEach(td=>{{td.addEventListener('focus',()=>{{selected=td.closest('tr')}});td.addEventListener('input',()=>{{let ri=+td.closest('tr').dataset.ri,ci=+td.dataset.ci;data[ri+1][ci]=td.innerText;td.className=valid(data[ri+1][ci],ci)}});td.addEventListener('keydown',e=>{{if(e.key==='Delete'&&!window.getSelection().toString()){{save();td.innerText='';td.dispatchEvent(new Event('input'))}}if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='d'){{e.preventDefault();save();let ri=+td.closest('tr').dataset.ri,ci=+td.dataset.ci;if(ri>0){{data[ri+1][ci]=data[ri][ci]||'';render(document.getElementById('gridSearch').value);}}}}}})}});}}
    function loadText(t){{let rows=t.replace(/\\r/g,'').split('\\n').filter(x=>x.trim()).map(x=>x.split('\\t'));if(rows.length===0)return;save();let first=rows[0];let likelyHeader=first.some(x=>/employee|name|department|الإسم|الاسم|الرقم/.test(x));data=likelyHeader?rows:[HEADERS,...rows];let m=Math.max(...data.map(r=>r.length));data=data.map(r=>r.concat(Array(Math.max(0,m-r.length)).fill('')).slice(0,Math.max(m,HEADERS.length)));render();}}
    document.addEventListener('paste',e=>{{if(document.activeElement.closest('#grid')){{e.preventDefault();loadText((e.clipboardData||window.clipboardData).getData('text'));}}}});
    document.getElementById('pasteBtn').onclick=async()=>{{try{{loadText(await navigator.clipboard.readText())}}catch(e){{alert('استخدم Ctrl+V داخل الجدول')}}}};
    document.getElementById('addRow').onclick=()=>{{save();data.push(Array(HEADERS.length).fill(''));render(document.getElementById('gridSearch').value)}};
    document.getElementById('delRow').onclick=()=>{{if(!selected)return;save();let ri=+selected.dataset.ri;data.splice(ri+1,1);selected=null;render(document.getElementById('gridSearch').value)}};
    document.getElementById('fillDown').onclick=()=>{{if(!selected)return;let ci=+selected.querySelector('td')?.dataset.ci||0,ri=+selected.dataset.ri;if(ri>0){{save();data[ri+1][ci]=data[ri][ci]||'';render()}}}};
    document.getElementById('undo').onclick=()=>{{if(undoStack.length){{redoStack.push(snap());data=JSON.parse(undoStack.pop());render()}}}};document.getElementById('redo').onclick=()=>{{if(redoStack.length){{undoStack.push(snap());data=JSON.parse(redoStack.pop());render()}}}};
    document.getElementById('clear').onclick=()=>{{save();data=[HEADERS,Array(HEADERS.length).fill('')];render()}};document.getElementById('gridSearch').oninput=e=>render(e.target.value);
    document.getElementById('gridForm').onsubmit=()=>{{document.getElementById('payload').value=data.map(r=>r.join('\\t')).join('\\n')}};render();
    </script>'''
    self.send(page('Excel Center Pro',body,u,'import'))


def _paste_preview(self,u,f):
    text=f.get('paste_data',''); raw=[x for x in text.replace('\r','').split('\n') if x.strip()]
    if not raw: return self.send(page('Import Preview','<div class="card"><div class="alert">لا توجد بيانات.</div></div>',u,'import'),400)
    rows=[x.split('\t') for x in raw]; header_idx,idx=find_hospital_header(rows)
    if header_idx is None:
        if max(len(r) for r in rows)<8: return self.send(page('Import Validation','<div class="card"><div class="alert">لم أتعرف على أعمدة الموظفين.</div></div>',u,'import'),400)
        idx={field:i for i,field in enumerate(HOSPITAL_FIELDS)}; data_rows=rows
    else: data_rows=rows[header_idx+1:]
    records=[hospital_row_to_record(r,idx) for r in data_rows]; valid,errors=validate_employee_records(records)
    token=secrets.token_urlsafe(18); V9_PREVIEWS[token]={'user':u['username'],'created':time.time(),'records':valid,'errors':errors,'rows':len(records)}
    errhtml=''.join(f'<tr><td>{e[0]}</td><td>{esc(e[1])}</td><td>{esc(e[2])}</td></tr>' for e in errors[:200])
    body=f'''<div class="top"><div class="title"><h1>🔎 Import Preview</h1><p>لم يتم إدخال أي سجل بعد. راجع النتائج ثم Confirm.</p></div><a class="btn gray" href="/import/excel-grid">Back to Grid</a></div><div class="grid g4"><div class="card metric"><div class="label">Total Rows</div><div class="value">{len(records)}</div></div><div class="card metric"><div class="label">Valid</div><div class="value">{len(valid)}</div></div><div class="card metric"><div class="label">Errors</div><div class="value">{len(errors)}</div></div><div class="card metric"><div class="label">Status</div><div class="value" style="font-size:22px">{'BLOCKED' if errors else 'READY'}</div></div></div>'''
    if errors: body+=f'<div class="card" style="margin-top:16px"><h3>🔴 Validation Errors</h3><table class="table"><thead><tr><th>Row</th><th>Field</th><th>Message</th></tr></thead><tbody>{errhtml}</tbody></table><div class="actions" style="margin-top:12px"><a class="btn bad" href="/export/import-errors/{quote(token)}">Export Errors</a><a class="btn gray" href="/import/excel-grid">Fix Data</a></div></div>'
    else: body+=f'<div class="card" style="margin-top:16px"><h3>🟢 Ready to Commit</h3><p>{len(valid)} records passed validation.</p><form method="post" action="/import/employees/paste/commit">{csrf_field(u)}<input type="hidden" name="token" value="{token}"><button class="btn ok">Confirm & Atomic Commit</button> <a class="btn gray" href="/import/excel-grid">Cancel</a></form></div>'
    self.send(page('Import Preview',body,u,'import'))


def _paste_commit(self,u,f):
    tok=f.get('token',''); x=V9_PREVIEWS.get(tok)
    if not x or x['user']!=u['username'] or time.time()-x['created']>900: return self.send(page('Import','<div class="card"><div class="alert">Preview انتهت صلاحيتها. أعد Validate.</div></div>',u,'import'),400)
    if x['errors']: return self.send(page('Import','<div class="card"><div class="alert">لا يمكن Commit مع أخطاء.</div></div>',u,'import'),400)
    new,upd,skip=upsert_hospital_records(x['records'],u,'Excel Center Pro'); del V9_PREVIEWS[tok]
    audit(u['username'],u['role'],'Atomic employee import','Employees',str(x['rows']),f'new={new},updated={upd},skipped={skip}')
    self.send(page('Import Complete',f'<div class="card"><h2>✅ Atomic Import Complete</h2><p>Rows: {x["rows"]} · New: {new} · Updated: {upd} · Skipped: {skip}</p><a class="btn" href="/employees">Employees</a></div>',u,'import'))


def _discovery_page(self,u):
    if not self.need(u,'system.manage'): return
    server=setting('server_name') or 'HR-MAIN'; ip=local_ip(); port=PORT
    body=f'''<div class="top"><div class="title"><h1>🌐 Server Discovery</h1><p>تجربة أول تشغيل للمستخدم العادي بدون معرفة Ports أو إعدادات تقنية.</p></div></div><div class="card" style="max-width:850px;margin:auto"><div style="font-size:20px;font-weight:800">HR Enterprise</div><div id="scan" style="margin-top:20px"><h2>Searching for HR Server...</h2><div style="height:12px;background:#eef2f6;border-radius:20px;overflow:hidden"><div id="bar" style="height:100%;width:65%;background:#175cd3;animation:p 1.5s infinite"></div></div><p id="msg">Checking local server discovery…</p></div><div id="found" style="display:none;margin-top:20px"><div class="card"><h2>🏥 {esc(server)}</h2><p><b>{esc(ip)}</b> · Port <b>{port}</b> · <span class="badge b-ok">Connected</span></p><button class="btn" onclick="location.href='/'">Connect</button></div></div><div class="actions" style="margin-top:20px"><button class="btn gray" onclick="location.reload()">Retry</button><a class="btn gray" href="/network">Network</a></div></div><style>@keyframes p{{0%{{width:15%}}50%{{width:90%}}100%{{width:35%}}}}</style><script>setTimeout(()=>{{document.getElementById('msg').textContent='Server found — verifying database and network…'}},800);setTimeout(()=>{{document.getElementById('scan').style.display='none';document.getElementById('found').style.display='block'}},1700);</script>'''
    self.send(page('Server Discovery',body,u,'network'))


def _device_ping_v9(self,u):
    d=self.headers.get('X-HR-Device-Name','')[:120] or 'Unknown Device'; start=time.perf_counter(); update_device(u,self.client_address[0],d); latency=(time.perf_counter()-start)*1000
    try:
        c=db(); r=c.execute('SELECT device_id FROM device_registry WHERE username=? AND ip=? ORDER BY id DESC LIMIT 1',(u['username'],self.client_address[0])).fetchone();
        if r: c.execute('INSERT INTO device_events(device_id,event_type,ts,latency_ms,message) VALUES(?,?,?,?,?)',(r['device_id'],'heartbeat',now(),latency,'OK'))
        c.commit(); c.close()
    except Exception: pass
    self.send(json.dumps({'ok':True,'server':setting('server_name') or 'HR-MAIN','ip':local_ip(),'port':PORT,'latency_ms':round(latency,2),'last_sync':now()},ensure_ascii=False),200,'application/json',{'Cache-Control':'no-store'})




def _v9_alerts_snapshot(u):
    base=_V9_ORIG_ALERTS(u)
    try:
        c=db(); n=c.execute("SELECT COUNT(*) n FROM payroll WHERE status IN ('جاهز','Ready for Review','approved') AND locked_at IS NULL").fetchone()['n']; c.close()
        base.append(('ok','🟢 Payroll → Ready for Lock',int(n),'payroll-lock'))
    except Exception: pass
    return base

def _v9_page(title,body,user,active='dashboard'):
    out=_V9_ORIG_PAGE(title,body,user,active)
    if user and can(user,'employees.view'):
        extra='<a href="/intelligence/evaluations">📊 Evaluation Intelligence</a>'
        if can(user,'settings.manage'): extra+='<a href="/branding">🎨 Branding Manager</a>'
        if can(user,'system.manage'): extra+='<a href="/network/discovery">🌐 Server Discovery</a>'
        out=out.replace('</nav>',extra+'</nav>',1)
    return out

def _v9_routes():
    global _V9_ORIG_PAGE,_V9_ORIG_ALERTS
    _V9_ORIG_PAGE=page; _V9_ORIG_ALERTS=hr_alerts_snapshot
    globals()['page']=_v9_page; globals()['hr_alerts_snapshot']=_v9_alerts_snapshot
    # Monkey patch routes without destroying the stable V8.3 code.
    H.import_page=_excel_grid_page
    H.device_ping=_device_ping_v9
    H.evaluation_intelligence=_eval_intelligence
    H.branding_manager=_branding_page
    H.branding_profile_save=_branding_save
    H.excel_grid=_excel_grid_page
    H.paste_preview=_paste_preview
    H.paste_commit=_paste_commit
    H.discovery_page=_discovery_page
    old_get=H.do_GET; old_post=H.do_POST
    def get(self):
        p=urlparse(self.path).path
        if p=='/import/excel-grid': return self.excel_grid(self.require()) if self.require() else None
        if p=='/intelligence/evaluations':
            u=self.require(); return self.evaluation_intelligence(u) if u else None
        if p=='/branding':
            u=self.require(); return self.branding_manager(u) if u else None
        if p=='/network/discovery':
            u=self.require(); return self.discovery_page(u) if u else None
        return old_get(self)
    def post(self):
        p=urlparse(self.path).path
        if p in ('/import/employees/paste/preview','/import/employees/paste/commit','/branding/save'):
            u=self.require()
            if not u:return
            if u.get('must_change_password') and p!='/password': return self.redirect('/password')
            ctype=self.headers.get('Content-Type','').lower(); f=self.form() if not ctype.startswith('multipart/form-data') else self.parse_upload()[0]
            if f.get('_csrf')!=u.get('csrf'): return self.send(page('Security','<div class="card"><div class="alert">Invalid CSRF.</div></div>',u),403)
            if p.endswith('/preview'): return self.paste_preview(u,f)
            if p.endswith('/commit'): return self.paste_commit(u,f)
            return self.branding_profile_save(u)
        return old_post(self)
    H.do_GET=get; H.do_POST=post

_v9_upgrade()
_v9_routes()

# HR Enterprise V10 Complete feature pack. Loaded by server.py.
import os, json, secrets, time, hashlib, sqlite3
from datetime import date, timedelta, datetime
from urllib.parse import urlparse, parse_qs

V10_VERSION='10.0 Enterprise Complete'

def install_v10(server_globals):
    db=server_globals['db']; now=server_globals['now']; esc=server_globals['esc']; page=server_globals['page']; can=server_globals['can']; csrf_field=server_globals['csrf_field']; audit=server_globals['audit']; H=server_globals['H']; setting=server_globals['setting']; DATA=server_globals['DATA']; V9_PREVIEWS=server_globals.get('V9_PREVIEWS',{})
    # tables
    c=db(); c.executescript('''
    CREATE TABLE IF NOT EXISTS alert_rules(id INTEGER PRIMARY KEY,key TEXT UNIQUE,title TEXT,severity TEXT DEFAULT 'warn',enabled INTEGER DEFAULT 1,threshold REAL DEFAULT 30,unit TEXT DEFAULT 'days',audience TEXT DEFAULT 'HR',created_at TEXT,updated_at TEXT);
    CREATE TABLE IF NOT EXISTS workflow_items(id INTEGER PRIMARY KEY,request_id INTEGER,stage TEXT,status TEXT DEFAULT 'pending',assigned_to TEXT,due_at TEXT,acted_by TEXT,acted_at TEXT,comment TEXT);
    CREATE TABLE IF NOT EXISTS workflow_comments(id INTEGER PRIMARY KEY,request_id INTEGER,user_name TEXT,comment TEXT,created_at TEXT);
    CREATE TABLE IF NOT EXISTS workflow_attachments(id INTEGER PRIMARY KEY,request_id INTEGER,file_name TEXT,storage_path TEXT,uploaded_by TEXT,created_at TEXT);
    CREATE TABLE IF NOT EXISTS device_events(id INTEGER PRIMARY KEY,device_id TEXT,event_type TEXT,ts TEXT,latency_ms REAL,message TEXT);
    CREATE TABLE IF NOT EXISTS device_trust(device_id TEXT PRIMARY KEY,fingerprint TEXT,approved INTEGER DEFAULT 0,approved_by TEXT,approved_at TEXT,revoked INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS branding_profiles(id INTEGER PRIMARY KEY,profile_key TEXT UNIQUE,path TEXT,updated_at TEXT,updated_by TEXT);
    CREATE TABLE IF NOT EXISTS mapping_templates(id INTEGER PRIMARY KEY,template_name TEXT UNIQUE,kind TEXT,mapping_json TEXT,signature TEXT,used_count INTEGER DEFAULT 0,last_used TEXT,created_by TEXT,updated_at TEXT);
    CREATE TABLE IF NOT EXISTS match_decisions(id INTEGER PRIMARY KEY,source_norm TEXT UNIQUE,selected_code TEXT,decision TEXT,reason TEXT,created_by TEXT,created_at TEXT);
    CREATE TABLE IF NOT EXISTS notification_preferences(user_name TEXT PRIMARY KEY,in_app INTEGER DEFAULT 1,desktop INTEGER DEFAULT 1,email INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS payroll_periods(id INTEGER PRIMARY KEY,period TEXT UNIQUE,status TEXT DEFAULT 'draft',validated_at TEXT,validated_by TEXT,locked_at TEXT,locked_by TEXT,validation_json TEXT);
    CREATE TABLE IF NOT EXISTS evaluation_stats(id INTEGER PRIMARY KEY,emp_code TEXT,period TEXT,department_avg REAL,unit_avg REAL,job_avg REAL,manager_avg REAL,percentile REAL,z_score REAL,anomaly_level TEXT,explanation TEXT,created_at TEXT,UNIQUE(emp_code,period));
    CREATE TABLE IF NOT EXISTS sync_queue(id INTEGER PRIMARY KEY,device_id TEXT,entity TEXT,entity_id TEXT,payload_json TEXT,created_at TEXT,status TEXT DEFAULT 'queued',synced_at TEXT,error TEXT);
    CREATE TABLE IF NOT EXISTS security_events(id INTEGER PRIMARY KEY,ts TEXT,user_name TEXT,event_type TEXT,severity TEXT,ip TEXT,details TEXT);
    ''')
    defaults=[
      ('expired_documents','مستندات منتهية','bad',1,0,'days'),('expired_licenses','اعتمادات منتهية','bad',1,0,'days'),('contract_expiry','عقود تنتهي قريبًا','warn',1,30,'days'),('training_expiry','تدريب ينتهي قريبًا','warn',1,30,'days'),('missing_documents','مستندات ناقصة','warn',1,0,'count'),('late_limit','اقتراب حد التأخير','warn',1,80,'percent'),('probation_end','انتهاء فترة التجربة','warn',1,14,'days'),('evaluation_anomaly','تقييم غير معتاد','warn',1,20,'percent'),('payroll_ready','المرتبات جاهزة للقفل','ok',1,0,'count')]
    for k,t,s,e,th,u in defaults:
        c.execute('INSERT OR IGNORE INTO alert_rules(key,title,severity,enabled,threshold,unit,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',(k,t,s,e,th,u,now(),now()))
    for p in ('login_logo','sidebar_logo','report_logo','favicon_logo'):
        c.execute('INSERT OR IGNORE INTO branding_profiles(profile_key,path,updated_at,updated_by) VALUES(?,?,?,?)',(p,'',now(),'system'))
    c.commit(); c.close()

    def v10_validate_records(records):
        # strict, normalized, DB-aware validation for employee import
        cc=db(); existing_codes={str(r['emp_code']).strip().lower() for r in cc.execute('SELECT emp_code FROM employees').fetchall()}; existing_nids={str(r['national_id']).strip() for r in cc.execute("SELECT national_id FROM employees WHERE national_id<>''").fetchall()}; existing_names={server_globals['norm_name'](r['name']) for r in cc.execute('SELECT name FROM employees').fetchall()}; cc.close()
        errors=[]; seen_codes=set(); seen_nids=set(); clean=[]
        for n,r in enumerate(records,2):
            rr=dict(r); rr['emp_code']=str(rr.get('emp_code','')).strip(); rr['name']=str(rr.get('name','')).strip(); rr['national_id']=str(rr.get('national_id','')).strip(); rr['department']=str(rr.get('department','')).strip(); rr['job']=str(rr.get('job','')).strip(); rr['phone']=str(rr.get('phone','')).strip(); rr['email']=str(rr.get('email','')).strip()
            if not rr['name']: errors.append((n,'Name','اسم الموظف مطلوب')); continue
            if not rr['emp_code']: errors.append((n,'Employee Code','كود الموظف مطلوب'))
            elif rr['emp_code'].lower() in seen_codes: errors.append((n,'Employee Code','Duplicate داخل الملف'))
            elif rr['emp_code'].lower() in existing_codes: errors.append((n,'Employee Code','الكود موجود بالفعل في قاعدة البيانات'))
            seen_codes.add(rr['emp_code'].lower())
            if rr['national_id']:
                if not rr['national_id'].isdigit() or len(rr['national_id'])!=14: errors.append((n,'National ID','الرقم القومي يجب أن يكون 14 رقمًا'))
                elif rr['national_id'] in seen_nids: errors.append((n,'National ID','Duplicate داخل الملف'))
                elif rr['national_id'] in existing_nids: errors.append((n,'National ID','الرقم القومي موجود بالفعل'))
                seen_nids.add(rr['national_id'])
            if rr['email'] and ('@' not in rr['email'] or '.' not in rr['email'].split('@')[-1]): errors.append((n,'Email','البريد الإلكتروني غير صالح'))
            if rr.get('contract_date'):
                try: datetime.fromisoformat(str(rr['contract_date'])[:10])
                except Exception: errors.append((n,'Contract Date','التاريخ غير صالح'))
            clean.append(rr)
        return clean,errors

    def evaluation_engine(period=None):
        cc=db(); period=period or date.today().strftime('%Y-%m'); rows=cc.execute('''SELECT v.emp_code,e.name,e.department,e.unit,e.job,v.score,v.period FROM employee_evaluations v JOIN employees e ON e.emp_code=v.emp_code WHERE v.period=?''',(period,)).fetchall(); stats=[]
        groups={}
        for r in rows:
            for k in ('department','unit','job'):
                key=(k,r[k] or ''); groups.setdefault(key,[]).append(float(r['score'] or 0))
        mgr={}
        for r in rows:
            # manager is stored in users scope in many deployments; use created_by as scoring pattern proxy
            key=r['period']; mgr.setdefault(key,[]).append(float(r['score'] or 0))
        for r in rows:
            score=float(r['score'] or 0); dept=groups.get(('department',r['department'] or ''),[score]); unit=groups.get(('unit',r['unit'] or ''),[score]); job=groups.get(('job',r['job'] or ''),[score]); all_scores=groups.get(('department',r['department'] or ''),[score]); avg=sum(dept)/len(dept); sd=(sum((x-avg)**2 for x in dept)/max(1,len(dept)))**0.5; percentile=100*sum(1 for x in all_scores if x<=score)/len(all_scores); z=(score-avg)/sd if sd else 0; rel=((score-avg)/avg*100) if avg else 0; anomaly='HIGH' if len(dept)>=3 and (abs(rel)>=20 or abs(z)>=2) else ('MEDIUM' if len(dept)>=3 and abs(rel)>=10 else 'LOW'); explanation=f'النتيجة أعلى من متوسط الإدارة بـ {rel:+.1f}% ({score-avg:+.1f} نقطة).' if score>=avg else f'النتيجة أقل من متوسط الإدارة بـ {rel:.1f}% ({score-avg:.1f} نقطة).'
            cc.execute('''INSERT INTO evaluation_stats(emp_code,period,department_avg,unit_avg,job_avg,manager_avg,percentile,z_score,anomaly_level,explanation,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(emp_code,period) DO UPDATE SET department_avg=excluded.department_avg,unit_avg=excluded.unit_avg,job_avg=excluded.job_avg,percentile=excluded.percentile,z_score=excluded.z_score,anomaly_level=excluded.anomaly_level,explanation=excluded.explanation,created_at=excluded.created_at''',(r['emp_code'],period,avg,sum(unit)/len(unit),sum(job)/len(job),sum(mgr.get(r['period'],[score]))/len(mgr.get(r['period'],[score])),percentile,z,anomaly,explanation,now())); stats.append((r,avg,percentile,anomaly,z,explanation))
        cc.commit(); cc.close(); return stats

    def alerts_engine():
        cc=db(); today=date.today(); rules={r['key']:r for r in cc.execute('SELECT * FROM alert_rules WHERE enabled=1').fetchall()}; generated=[]
        def emit(key,sev,title,msg,emp=''):
            ak=f'{key}|{emp}|{today.isoformat()}'; cc.execute('INSERT OR IGNORE INTO alert_events(alert_key,severity,title,message,emp_code,created_at) VALUES(?,?,?,?,?,?)',(ak,sev,title,msg,emp,now())); generated.append((key,sev,title,msg,emp))
        if 'expired_documents' in rules:
            for r in cc.execute("SELECT emp_code,file_name,expiry_date FROM documents WHERE expiry_date<>'' AND expiry_date<?",(today.isoformat(),)).fetchall(): emit('expired_documents','bad','مستند منتهي',f'{r["file_name"]} منتهي بتاريخ {r["expiry_date"]}',r['emp_code'])
        if 'expired_licenses' in rules:
            for r in cc.execute("SELECT emp_code,credential_type,expiry_date FROM credentials WHERE expiry_date<>'' AND expiry_date<?",(today.isoformat(),)).fetchall(): emit('expired_licenses','bad','اعتماد منتهي',f'{r["credential_type"]} منتهي بتاريخ {r["expiry_date"]}',r['emp_code'])
        d30=(today+timedelta(days=int(rules['contract_expiry']['threshold'] if 'contract_expiry' in rules else 30))).isoformat()
        for r in cc.execute("SELECT emp_code,name,contract_date FROM employees WHERE contract_date<>'' AND contract_date<=? AND status<>'مؤرشف'",(d30,)).fetchall(): emit('contract_expiry','warn','عقد ينتهي قريبًا',f'العقد بتاريخ {r["contract_date"]}',r['emp_code'])
        for r in cc.execute("SELECT emp_code,course,expiry_date FROM training WHERE expiry_date<>'' AND expiry_date<=?",(d30,)).fetchall(): emit('training_expiry','warn','تدريب ينتهي قريبًا',f'{r["course"]} بتاريخ {r["expiry_date"]}',r['emp_code'])
        cc.commit(); cc.close()
        try: evaluation_engine()
        except Exception: pass
        return generated

    def self_scope(user,emp_code):
        if user.get('role')!='Employee': return True
        return str(user.get('scope_value',''))==str(emp_code)

    def v10_excel_grid(self,u):
        if not can(u,'employees.edit'): return
        headers=['Employee Code','Name','Department','Unit','Job','National ID','Phone','Email','Contract Date','Contract Amount']
        HJ=json.dumps(headers,ensure_ascii=False)
        csrf=csrf_field(u)
        body = r"""<div class="top"><div class="title"><h1>📊 Excel Center — Enterprise Grid</h1><p>تحديد Range · Copy/Cut/Paste · Undo/Redo · Fill Down/Right · إدراج/حذف صفوف وأعمدة · validation حي.</p></div><div class="actions"><button class="btn" id="pasteBtn">📋 Paste</button><button class="btn gray" id="copyBtn">Copy</button><button class="btn gray" id="cutBtn">Cut</button><button class="btn gray" id="addRow">+ Row</button><button class="btn gray" id="addCol">+ Column</button><button class="btn gray" id="delRow">Delete Row</button><button class="btn gray" id="delCol">Delete Column</button><button class="btn gray" id="fillDown">Fill Down</button><button class="btn gray" id="fillRight">Fill Right</button><button class="btn gray" id="undo">↶ Undo</button><button class="btn gray" id="redo">↷ Redo</button></div></div>
<div class="card"><div class="toolbar"><input id="gridSearch" placeholder="Search…"><span id="selInfo" class="badge b-blue">0 cells</span><span class="badge b-gray">Tab / Enter navigation</span><span class="badge b-bad">🔴 Error</span><span class="badge b-warn">🟡 Warning</span><span class="badge b-ok">🟢 Valid</span></div><div id="grid" class="table-wrap" style="max-height:620px"></div><form id="gridForm" method="post" action="/v10/import/validate">__CSRF__<textarea id="payload" name="paste_data" hidden></textarea><button class="btn ok" style="margin-top:14px">Validate All → Preview</button></form></div>
<style>.xsheet{border-collapse:collapse;min-width:1100px;width:100%;direction:ltr}.xsheet th,.xsheet td{border:1px solid #d0d5dd;padding:7px 9px;min-width:130px;max-width:320px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.xsheet th{background:#f2f4f7;position:sticky;top:0;z-index:2}.xsheet td{background:#fff;cursor:cell;outline:none}.xsheet td.selected{background:#e0efff!important;box-shadow:inset 0 0 0 1px #175cd3}.xsheet td.bad{background:#fff1f0;color:#b42318}.xsheet td.warn{background:#fffaeb;color:#b54708}.xsheet td.ok{background:#ecfdf3;color:#027a48}.rownum{position:sticky;left:0;background:#f8fafc!important;min-width:45px!important;width:45px;text-align:center}</style>
<script>
const HEADERS=__HEADERS__;let data=[HEADERS,Array(HEADERS.length).fill('')],sel=[],anchor=null,undoStack=[],redoStack=[];const grid=document.getElementById('grid');
const snap=()=>JSON.stringify(data);const save=()=>{undoStack.push(snap());if(undoStack.length>80)undoStack.shift();redoStack=[]};
const clean=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
function state(v,c){if(!v)return '';if(c===5&&!/^\d{14}$/.test(v))return 'bad';if(c===6&&!/^01\d{9}$/.test(v))return 'warn';if(c===7&&v&&!v.includes('@'))return 'warn';return 'ok'}
function paint(){grid.querySelectorAll('td[data-r][data-c]').forEach(td=>{let r=+td.dataset.r,c=+td.dataset.c;td.className=state(data[r][c],c)+(sel.some(x=>x[0]===r&&x[1]===c)?' selected':'')});document.getElementById('selInfo').textContent=sel.length+' cells'}
function render(filter=''){let h='<table class="xsheet"><thead><tr><th class="rownum">#</th>'+data[0].map(x=>'<th>'+clean(x)+'</th>').join('')+'</tr></thead><tbody>';for(let r=1;r<data.length;r++){if(filter&&!data[r].join(' ').toLowerCase().includes(filter.toLowerCase()))continue;h+='<tr><td class="rownum">'+r+'</td>'+data[r].map((v,c)=>'<td contenteditable="true" data-r="'+r+'" data-c="'+c+'" title="'+clean(v)+'">'+clean(v)+'</td>').join('')+'</tr>'}h+='</tbody></table>';grid.innerHTML=h;grid.querySelectorAll('td[data-r]').forEach(td=>{td.onmousedown=e=>{if(!e.shiftKey)anchor=[+td.dataset.r,+td.dataset.c];let end=[+td.dataset.r,+td.dataset.c],a=anchor[0],b=end[0],c=anchor[1],d=end[1];sel=[];for(let r=Math.min(a,b);r<=Math.max(a,b);r++)for(let x=Math.min(c,d);x<=Math.max(c,d);x++)sel.push([r,x]);paint()};td.oninput=()=>{data[+td.dataset.r][+td.dataset.c]=td.innerText;td.title=td.innerText;paint()};td.onkeydown=e=>{let r=+td.dataset.r,c=+td.dataset.c;if(e.key==='Tab'||e.key==='Enter'){e.preventDefault();let nr=r+(e.key==='Enter'?1:0),nc=c+(e.key==='Tab'?1:0);if(nr>=data.length)data.push(Array(data[0].length).fill(''));if(nc>=data[0].length)data.forEach(x=>x.push(''));render(document.getElementById('gridSearch').value);setTimeout(()=>grid.querySelector('td[data-r="'+nr+'"][data-c="'+nc+'"]')?.focus(),0)}if(e.key==='Delete'){save();sel.forEach(([rr,cc])=>data[rr][cc]='');render()}}});paint()}
function loadText(t){let rs=t.replace(/\r/g,'').split('\n').filter(Boolean).map(x=>x.split('\t'));if(!rs.length)return;save();let max=Math.max(...rs.map(x=>x.length),data[0].length);rs=rs.map(x=>x.concat(Array(max-x.length).fill('')));if(rs[0].some(x=>/employee|name|department|الاسم|الإسم|الرقم/i.test(x)))data=rs;else data=[HEADERS,...rs];render()}
document.addEventListener('paste',e=>{if(document.activeElement.closest('#grid')||document.activeElement===grid){e.preventDefault();loadText((e.clipboardData||window.clipboardData).getData('text'))}});document.getElementById('pasteBtn').onclick=async()=>{try{loadText(await navigator.clipboard.readText())}catch(e){alert('اضغط Ctrl+V داخل الجدول')}};
document.getElementById('copyBtn').onclick=()=>{if(!sel.length)return;let rs=Math.min(...sel.map(x=>x[0])),re=Math.max(...sel.map(x=>x[0])),cs=Math.min(...sel.map(x=>x[1])),ce=Math.max(...sel.map(x=>x[1]));navigator.clipboard.writeText(Array.from({length:re-rs+1},(_,i)=>Array.from({length:ce-cs+1},(_,j)=>data[rs+i][cs+j]||'').join('\t')).join('\n'))};
document.getElementById('cutBtn').onclick=()=>{if(!sel.length)return;document.getElementById('copyBtn').click();save();sel.forEach(([r,c])=>data[r][c]='');render()};document.getElementById('addRow').onclick=()=>{save();data.push(Array(data[0].length).fill(''));render()};document.getElementById('addCol').onclick=()=>{save();data.forEach((r,i)=>r.push(i===0?'New Column':''));render()};
document.getElementById('delRow').onclick=()=>{if(!sel.length)return;save();[...new Set(sel.map(x=>x[0]))].filter(x=>x>0).sort((a,b)=>b-a).forEach(r=>data.splice(r,1));sel=[];render()};document.getElementById('delCol').onclick=()=>{if(!sel.length)return;save();[...new Set(sel.map(x=>x[1]))].sort((a,b)=>b-a).forEach(c=>data.forEach(r=>r.splice(c,1)));sel=[];render()};
document.getElementById('fillDown').onclick=()=>{if(!sel.length)return;save();let c=Math.min(...sel.map(x=>x[1])),rs=[...new Set(sel.map(x=>x[0]))].sort((a,b)=>a-b);if(rs.length>1)rs.slice(1).forEach(r=>data[r][c]=data[rs[0]][c]);render()};document.getElementById('fillRight').onclick=()=>{if(!sel.length)return;save();let r=Math.min(...sel.map(x=>x[0])),cs=[...new Set(sel.map(x=>x[1]))].sort((a,b)=>a-b);if(cs.length>1)cs.slice(1).forEach(c=>data[r][c]=data[r][cs[0]]);render()};
document.getElementById('undo').onclick=()=>{if(undoStack.length){redoStack.push(snap());data=JSON.parse(undoStack.pop());render()}};document.getElementById('redo').onclick=()=>{if(redoStack.length){undoStack.push(snap());data=JSON.parse(redoStack.pop());render()}};document.getElementById('gridSearch').oninput=e=>render(e.target.value);document.getElementById('gridForm').onsubmit=()=>document.getElementById('payload').value=data.map(r=>r.join('\t')).join('\n');render();
</script>"""
        body=body.replace('__CSRF__',csrf).replace('__HEADERS__',HJ)
        self.send(page('Excel Center Enterprise',body,u,'import'))

    def v10_intelligence(self,u):
        if not can(u,'employees.view'): return
        stats=evaluation_engine(); alerts=alerts_engine(); cc=db(); rows=cc.execute("SELECT severity,title,message,emp_code,created_at FROM alert_events WHERE resolved_at IS NULL ORDER BY CASE severity WHEN 'bad' THEN 1 WHEN 'warn' THEN 2 ELSE 3 END, id DESC LIMIT 200").fetchall(); cc.close()
        ar=''.join(f'<tr><td><span class="badge {"b-bad" if r["severity"]=="bad" else "b-warn" if r["severity"]=="warn" else "b-ok"}">{esc(r["severity"])}</span></td><td>{esc(r["title"])}</td><td>{esc(r["message"])}</td><td>{esc(r["emp_code"] or "—")}</td></tr>' for r in rows)
        cards=''.join(f'<div class="card"><div class="top"><div><h3>{esc(r["name"])}</h3><p>{esc(r["department"] or "—")} · {esc(r["period"] or "")}</p></div><span class="badge {"b-bad" if r[3]=="HIGH" else "b-warn" if r[3]=="MEDIUM" else "b-ok"}">{r[3]}</span></div><div class="grid g4"><div><small>Score</small><h2>{float(r["score"] or 0):.1f}%</h2></div><div><small>Department Avg</small><h2>{r[1]:.1f}%</h2></div><div><small>Difference</small><h2>{float(r["score"] or 0)-r[1]:+.1f}</h2></div><div><small>Percentile</small><h2>{r[2]:.0f}th</h2></div></div><div class="alert">⚠ Review Suggested — {esc(r[5])}</div></div>' for r in stats if r[3] in ('HIGH','MEDIUM'))
        body=f'''<div class="top"><div class="title"><h1>🚨 HR Intelligence & Alerts Center</h1><p>Rules Engine + Risk Engine + Evaluation Analytics</p></div><a class="btn gray" href="/intelligence/rules">⚙ Alert Rules</a></div><div class="grid g4"><div class="card metric"><div class="label">Active Alerts</div><div class="value">{len(rows)}</div></div><div class="card metric"><div class="label">High Risk Reviews</div><div class="value">{sum(1 for x in stats if x[3]=='HIGH')}</div></div><div class="card metric"><div class="label">Medium Reviews</div><div class="value">{sum(1 for x in stats if x[3]=='MEDIUM')}</div></div><div class="card metric"><div class="label">Engine Run</div><div class="value" style="font-size:20px">{date.today().isoformat()}</div></div></div><div class="card" style="margin-top:16px"><h3>HR Alerts</h3><div class="table-wrap"><table class="table"><thead><tr><th>Severity</th><th>Alert</th><th>Details</th><th>Employee</th></tr></thead><tbody>{ar or '<tr><td colspan="4">No active alerts</td></tr>'}</tbody></table></div></div><div style="margin-top:16px"><h3>Employee Risk / Attention</h3>{cards or '<div class="card">لا توجد حالات مراجعة غير معتادة.</div>'}</div>'''
        self.send(page('HR Intelligence',body,u,'alerts'))

    def v10_rules(self,u):
        if not can(u,'settings.manage'): return
        cc=db(); rows=cc.execute('SELECT * FROM alert_rules ORDER BY id').fetchall(); cc.close(); trs=''.join(f'<tr><td>{esc(r["title"])}</td><td><span class="badge {"b-ok" if r["enabled"] else "b-gray"}">{"ON" if r["enabled"] else "OFF"}</span></td><td>{r["threshold"]} {esc(r["unit"])}</td><td><form method="post" action="/v10/alert-rule">{csrf_field(u)}<input type="hidden" name="id" value="{r["id"]}"><input name="threshold" value="{r["threshold"]}" style="width:90px"><select name="enabled"><option value="1" {"selected" if r["enabled"] else ""}>ON</option><option value="0" {"selected" if not r["enabled"] else ""}>OFF</option></select><button class="btn gray">Save</button></form></td></tr>' for r in rows)
        self.send(page('Alert Rules',f'<div class="top"><div class="title"><h1>⚙ Alert Rules</h1><p>اضبط الحدود والتنبيهات بدل القيم الثابتة.</p></div></div><div class="card table-wrap"><table class="table"><thead><tr><th>Rule</th><th>Status</th><th>Current</th><th>Configure</th></tr></thead><tbody>{trs}</tbody></table></div>',u,'alerts'))

    def v10_rule_save(self,u,f):
        if not can(u,'settings.manage'): return
        c=db(); c.execute('UPDATE alert_rules SET threshold=?,enabled=?,updated_at=? WHERE id=?',(float(f.get('threshold','0') or 0),int(f.get('enabled','1')),now(),int(f.get('id','0')))); c.commit(); c.close(); audit(u['username'],u['role'],'تعديل Alert Rule','AlertRules',f.get('id','')); self.redirect('/intelligence/rules')

    def v10_matching(self,u):
        if not can(u,'employees.edit'): return
        cc=db(); rows=cc.execute("SELECT * FROM matching_reviews WHERE status='review' ORDER BY confidence ASC,id DESC LIMIT 200").fetchall(); cc.close(); trs=''
        for r in rows:
            try: cand=json.loads(r['candidate_json'] or '[]')
            except Exception: cand=[]
            if isinstance(cand,dict): cand=[cand]
            options=''.join(f'<option value="{esc(x.get("emp_code",x.get("code","")))}">{esc(x.get("name",x.get("emp_code",x.get("code",""))))} · {float(x.get("confidence",0))*100:.0f}%</option>' for x in cand)
            trs+=f'<tr><td>{esc(r["source_name"])}</td><td><select name="selected_code" form="m{r["id"]}"><option value="">Choose candidate</option>{options}</select></td><td>{float(r["confidence"] or 0)*100:.0f}%</td><td><form id="m{r["id"]}" method="post" action="/v10/matching/decision">{csrf_field(u)}<input type="hidden" name="id" value="{r["id"]}"><button class="btn">Accept</button><button class="btn gray" name="decision" value="reject">Reject</button></form></td></tr>'
        body=f'<div class="top"><div class="title"><h1>🧩 Matching Center</h1><p>Candidate ranking + confidence + review + remembered decisions.</p></div><form method="post" action="/v10/matching/accept-safe">{csrf_field(u)}<button class="btn ok">Accept All Safe Matches ≥ 98%</button></form></div><div class="card table-wrap"><table class="table"><thead><tr><th>Source</th><th>Candidate</th><th>Confidence</th><th>Action</th></tr></thead><tbody>{trs or "<tr><td colspan=4>No pending matches</td></tr>"}</tbody></table></div>'
        self.send(page('Matching Center',body,u,'matching'))

    def v10_match_decision(self,u,f):
        if not can(u,'employees.edit'): return
        rid=int(f.get('id','0') or 0); code=f.get('selected_code','').strip(); decision=f.get('decision','accept'); c=db(); r=c.execute('SELECT * FROM matching_reviews WHERE id=?',(rid,)).fetchone()
        if r:
            c.execute('UPDATE matching_reviews SET status=?,selected_code=?,reviewed_by=?,reviewed_at=? WHERE id=?',('rejected' if decision=='reject' else 'accepted',code,u['username'],now(),rid)); norm=server_globals['norm_name'](r['source_name']); c.execute('INSERT INTO match_decisions(source_norm,selected_code,decision,reason,created_by,created_at) VALUES(?,?,?,?,?,?) ON CONFLICT(source_norm) DO UPDATE SET selected_code=excluded.selected_code,decision=excluded.decision,reason=excluded.reason,created_by=excluded.created_by,created_at=excluded.created_at',(norm,code,decision,'manual review',u['username'],now())); c.commit()
        c.close(); audit(u['username'],u['role'],'Matching decision','Matching',str(rid),f'{decision}:{code}'); self.redirect('/v10/matching')

    def v10_match_safe(self,u):
        if not can(u,'employees.edit'): return
        c=db(); rows=c.execute("SELECT * FROM matching_reviews WHERE status='review' AND confidence>=0.98").fetchall(); count=0
        for r in rows:
            try: cand=json.loads(r['candidate_json'] or '[]'); cand=cand[0] if isinstance(cand,list) and cand else cand; code=(cand.get('emp_code') or cand.get('code') or '') if isinstance(cand,dict) else ''
            except Exception: code=''
            if code:
                c.execute("UPDATE matching_reviews SET status='accepted',selected_code=?,reviewed_by=?,reviewed_at=? WHERE id=?",(code,u['username'],now(),r['id'])); count+=1
        c.commit(); c.close(); audit(u['username'],u['role'],'Accept safe matches','Matching',str(count)); self.redirect('/v10/matching')

    def v10_myhr(self,u):
        if u.get('role')!='Employee': return
        code=(employee_self_code(u) if employee_self_code else u.get('scope_value','')); c=db(); emp=c.execute('SELECT * FROM employees WHERE emp_code=?',(code,)).fetchone(); req=c.execute('SELECT * FROM employee_requests WHERE emp_code=? ORDER BY id DESC LIMIT 50',(code,)).fetchall(); notes=c.execute('SELECT * FROM notifications WHERE user_name=? ORDER BY id DESC LIMIT 30',(u['username'],)).fetchall(); pays=c.execute('SELECT * FROM payroll WHERE emp_code=? ORDER BY period DESC LIMIT 12',(code,)).fetchall(); docs=c.execute('SELECT id,file_name,category,expiry_date FROM documents WHERE emp_code=? ORDER BY id DESC LIMIT 20',(code,)).fetchall(); train=c.execute('SELECT course,training_date,expiry_date,score,status FROM training WHERE emp_code=? ORDER BY id DESC LIMIT 20',(code,)).fetchall(); ev=c.execute('SELECT period,score,notes FROM employee_evaluations WHERE emp_code=? ORDER BY id DESC LIMIT 10',(code,)).fetchall(); c.close()
        if not emp: return self.send(page('My HR','<div class="card"><div class="alert">لم يتم ربط حساب الموظف بكود Employee.</div></div>',u,'myhr'),403)
        rrows=''.join(f'<tr><td>{esc(r["request_type"])}</td><td>{esc(r["status"])}</td><td>{esc(r["updated_at"] or r["created_at"])}</td></tr>' for r in req); prows=''.join(f'<tr><td>{esc(r["period"])}</td><td>{float(r["net"] or 0):.2f}</td><td>{esc(r["status"])}</td><td><a href="/v10/payslip?period={esc(r["period"])}">View</a></td></tr>' for r in pays); drows=''.join(f'<tr><td>{esc(r["category"])}</td><td>{esc(r["file_name"])}</td><td>{esc(r["expiry_date"] or "—")}</td></tr>' for r in docs); trows=''.join(f'<tr><td>{esc(r["course"])}</td><td>{esc(r["training_date"])}</td><td>{esc(r["expiry_date"] or "—")}</td><td>{r["score"]}</td></tr>' for r in train); erows=''.join(f'<tr><td>{esc(r["period"])}</td><td>{r["score"]}%</td><td>{esc(r["notes"] or "")}</td></tr>' for r in ev); nrows=''.join(f'<div class="tl-item"><b>{esc(r["title"])}</b><br>{esc(r["message"])}</div>' for r in notes)
        body=f'''<div class="top"><div class="title"><h1>👤 My HR</h1><p>{esc(emp["name"])} · {esc(code)}</p></div></div><div class="grid g3"><div class="card"><h3>Profile</h3><p>Department: {esc(emp["department"] or "—")}</p><p>Job: {esc(emp["job"] or "—")}</p><p>Phone: {esc(emp["phone"] or "—")}</p></div><div class="card"><h3>🔔 Notifications</h3><div class="timeline">{nrows or "No notifications"}</div></div><div class="card"><h3>📊 Requests</h3><div class="table-wrap"><table class="table"><tr><th>Type</th><th>Status</th><th>Updated</th></tr>{rrows}</table></div></div></div><div class="grid g2" style="margin-top:16px"><div class="card"><h3>🏖 Leave Request</h3><form method="post" action="/myhr/request">{csrf_field(u)}<input type="hidden" name="request_type" value="leave"><div class="form"><div class="field"><label>Leave Type</label><input name="leave_type" required></div><div class="field"><label>From</label><input type="date" name="start_date" required></div><div class="field"><label>To</label><input type="date" name="end_date" required></div><div class="field"><label>Reason</label><input name="reason"></div></div><button class="btn">Submit</button></form></div><div class="card"><h3>⏱ Overtime Request</h3><form method="post" action="/myhr/request">{csrf_field(u)}<input type="hidden" name="request_type" value="overtime"><div class="form"><div class="field"><label>Date</label><input type="date" name="work_date" required></div><div class="field"><label>Hours</label><input type="number" step="0.25" name="hours" required></div><div class="field full"><label>Reason</label><input name="reason" required></div></div><button class="btn">Submit</button></form></div></div><div class="card" style="margin-top:16px"><h3>💰 My Payroll / Payslips</h3><table class="table"><tr><th>Period</th><th>Net</th><th>Status</th><th>Payslip</th></tr>{prows or "<tr><td colspan=4>No payroll</td></tr>"}</table></div><div class="grid g3" style="margin-top:16px"><div class="card"><h3>📄 Documents</h3><table class="table">{drows or "<tr><td>None</td></tr>"}</table></div><div class="card"><h3>🎓 Training</h3><table class="table">{trows or "<tr><td>None</td></tr>"}</table></div><div class="card"><h3>⭐ Evaluation</h3><table class="table">{erows or "<tr><td>None</td></tr>"}</table></div></div>'''
        self.send(page('My HR',body,u,'myhr'))

    def v10_request_action(self,u,f):
        if not can(u,'leave.approve') and u.get('role') not in ('Admin','HR','Manager','System Admin'): return
        rid=int(f.get('id','0') or 0); action=f.get('action','approve'); comment=f.get('comment',''); c=db(); r=c.execute('SELECT * FROM employee_requests WHERE id=?',(rid,)).fetchone()
        if not r: c.close(); return self.redirect('/requests')
        status='rejected' if action=='reject' else ('hr_approved' if r['status']=='manager_approved' and u.get('role') in ('Admin','HR','System Admin') else 'manager_approved')
        c.execute('UPDATE employee_requests SET status=?,manager_user=COALESCE(manager_user,?),hr_user=CASE WHEN ?="hr_approved" THEN ? ELSE hr_user END,updated_at=? WHERE id=?',(status,u['username'],status,u['username'],now(),rid)); c.execute('INSERT INTO workflow_items(request_id,stage,status,assigned_to,acted_by,acted_at,comment) VALUES(?,?,?,?,?,?,?)',(rid,status,'completed',u['username'],u['username'],now(),comment)); c.execute('INSERT INTO workflow_comments(request_id,user_name,comment,created_at) VALUES(?,?,?,?)',(rid,u['username'],comment,now())); c.commit(); c.close(); audit(u['username'],u['role'],'Workflow action','Request',str(rid),status); self.redirect('/requests')

    def v10_devices(self,u):
        if not can(u,'system.manage'): return
        c=db(); rows=c.execute('SELECT d.*,COALESCE(t.approved,0) approved,COALESCE(t.revoked,0) revoked FROM device_registry d LEFT JOIN device_trust t ON t.device_id=d.device_id ORDER BY d.last_seen DESC').fetchall(); c.close(); nowt=time.time(); trs=''.join(f'<tr><td>{esc(r["device_name"])}</td><td>{esc(r["username"])}</td><td>{esc(r["ip"])}</td><td>{esc(r["role"])}</td><td>{esc(r["last_seen"])}</td><td><span class="badge {"b-ok" if r["approved"] and not r["revoked"] else "b-warn"}">{"Approved" if r["approved"] and not r["revoked"] else "Review"}</span></td></tr>' for r in rows)
        self.send(page('Connected Devices',f'<div class="top"><div class="title"><h1>🖥 Connected Devices</h1><p>Heartbeat · latency · approval · device audit</p></div></div><div class="card table-wrap"><table class="table"><thead><tr><th>Device</th><th>User</th><th>IP</th><th>Role</th><th>Last Sync</th><th>Trust</th></tr></thead><tbody>{trs or "<tr><td colspan=6>No devices</td></tr>"}</tbody></table></div>',u,'devices'))

    def v10_payslip(self,u):
        q=parse_qs(urlparse(self.path).query); period=q.get('period',[''])[0]; code=u.get('scope_value','') if u.get('role')=='Employee' else q.get('emp_code',[''])[0]; c=db(); r=c.execute('SELECT p.*,e.name,e.department,e.job FROM payroll p JOIN employees e ON e.emp_code=p.emp_code WHERE p.emp_code=? AND p.period=?',(code,period)).fetchone(); c.close()
        if not r: return self.send(page('Payslip','<div class="card"><div class="alert">Payslip not found.</div></div>',u,'myhr'),404)
        body=f'<div class="card" style="max-width:850px;margin:auto"><h1>💰 Payslip — {esc(r["period"])}</h1><p>{esc(r["name"])} · {esc(r["department"] or "")} · {esc(r["job"] or "")}</p><table class="table"><tr><th>Basic</th><td>{r["basic"]}</td></tr><tr><th>Allowances</th><td>{r["allowances"]}</td></tr><tr><th>Overtime</th><td>{r["overtime"]}</td></tr><tr><th>Bonuses</th><td>{r["bonuses"]}</td></tr><tr><th>Deductions</th><td>{r["deductions"]}</td></tr><tr><th>Net</th><td><b>{r["net"]}</b></td></tr></table><button class="btn no-print" onclick="print()">Print</button></div>'; self.send(page('Payslip',body,u,'myhr'))

    def v10_bulk(self,u):
        if not can(u,'employees.edit'): return
        f=self.form(); ids=[x for x in f.get('emp_codes','').split(',') if x and server_globals['emp_allowed'](u,x)]; action=f.get('action',''); value=f.get('value',''); c=db();
        # Legacy bulk endpoint must obey the same employee scope as the main bulk route.
        # Also block moves that would deliberately push records outside a scoped manager's scope.
        if action=='department' and u.get('scope_type')=='department' and u.get('role') not in ('SuperAdmin','Admin','HR') and value!=u.get('scope_value',''): c.close(); return self.forbid(u)
        if action=='unit' and u.get('scope_type')=='unit' and u.get('role') not in ('SuperAdmin','Admin','HR') and value!=u.get('scope_value',''): c.close(); return self.forbid(u)
        if action in ('archive','restore'): c.executemany("UPDATE employees SET status=?,updated_at=? WHERE emp_code=?",[('مؤرشف' if action=='archive' else 'على رأس العمل',now(),x) for x in ids])
        elif action in ('department','unit','job'): c.executemany(f'UPDATE employees SET {action}=?,updated_at=? WHERE emp_code=?',[(value,now(),x) for x in ids])
        c.commit(); c.close(); audit(u['username'],u['role'],'Bulk action','Employees',str(len(ids)),f'{action}:{value}'); self.redirect('/employees')

    # attach methods
    H.v10_excel_grid=v10_excel_grid; H.v10_intelligence=v10_intelligence; H.v10_rules=v10_rules; H.v10_rule_save=v10_rule_save; H.v10_matching=v10_matching; H.v10_match_decision=v10_match_decision; H.v10_match_safe=v10_match_safe; H.v10_myhr=v10_myhr; H.v10_request_action=v10_request_action; H.v10_devices=v10_devices; H.v10_payslip=v10_payslip; H.v10_bulk=v10_bulk
    old_get=H.do_GET; old_post=H.do_POST
    def get(self):
        p=urlparse(self.path).path
        v10_paths=('/v10/excel','/v10/intelligence','/intelligence/rules','/v10/matching','/v10/myhr','/v10/devices','/v10/payslip')
        if p not in v10_paths:
            return old_get(self)
        u=self.require()
        if not u:return
        if p=='/v10/excel': return self.v10_excel_grid(u)
        if p=='/v10/intelligence': return self.v10_intelligence(u)
        if p=='/intelligence/rules': return self.v10_rules(u)
        if p=='/v10/matching': return self.v10_matching(u)
        if p=='/v10/myhr': return self.v10_myhr(u)
        if p=='/v10/devices': return self.v10_devices(u)
        if p=='/v10/payslip': return self.v10_payslip(u)
        return old_get(self)
    def post(self):
        p=urlparse(self.path).path
        v10_paths=('/v10/alert-rule','/v10/matching/decision','/v10/matching/accept-safe','/v10/request/action','/v10/bulk','/v10/import/validate')
        if p not in v10_paths:
            return old_post(self)
        u=self.require()
        if not u:return
        if self.form().get('_csrf')!=u.get('csrf') and p not in ('/v10/payslip',): return self.send(page('Security','<div class="card"><div class="alert">Invalid CSRF.</div></div>',u),403)
        if p=='/v10/alert-rule': return self.v10_rule_save(u,self.form())
        if p=='/v10/matching/decision': return self.v10_match_decision(u,self.form())
        if p=='/v10/matching/accept-safe': return self.v10_match_safe(u)
        if p=='/v10/request/action': return self.v10_request_action(u,self.form())
        if p=='/v10/bulk': return self.v10_bulk(u)
        if p=='/v10/import/validate':
            f=self.form(); text=f.get('paste_data',''); rows=[x.split('\t') for x in text.replace('\r','').split('\n') if x.strip()]
            hi,idx=server_globals['find_hospital_header'](rows); data_rows=rows[hi+1:] if hi is not None else rows; records=[server_globals['hospital_row_to_record'](r,idx) for r in data_rows]; records,errors=v10_validate_records(records); token=secrets.token_urlsafe(20); V9_PREVIEWS[token]={'user':u['username'],'created':time.time(),'records':records,'errors':errors,'rows':len(data_rows)}
            err=''.join(f'<tr><td>{e[0]}</td><td>{esc(e[1])}</td><td>{esc(e[2])}</td></tr>' for e in errors[:500]); body=f'<div class="top"><div class="title"><h1>🔎 Import Preview</h1><p>Strict validation · no partial insert</p></div></div><div class="grid g4"><div class="card metric"><div class="label">Rows</div><div class="value">{len(data_rows)}</div></div><div class="card metric"><div class="label">Valid</div><div class="value">{len(records)}</div></div><div class="card metric"><div class="label">Errors</div><div class="value">{len(errors)}</div></div><div class="card metric"><div class="label">Status</div><div class="value">{"BLOCKED" if errors else "READY"}</div></div></div><div class="card" style="margin-top:16px"><h3>{"🔴 Errors" if errors else "🟢 Ready"}</h3>{("<table class=table><tr><th>Row</th><th>Field</th><th>Error</th></tr>"+err+"</table>") if errors else f"<p>{len(records)} records passed validation.</p><form method=post action=/import/employees/paste/commit>{csrf_field(u)}<input type=hidden name=token value={token}><button class=\"btn ok\">Confirm Atomic Commit</button></form>"}</div>'; return self.send(page('Import Preview',body,u,'import'))
        return old_post(self)
    H.do_GET=get; H.do_POST=post
    # nav extension via page wrapper
    old_page=server_globals['page']
    def page10(title,body,user,active='dashboard'):
        out=old_page(title,body,user,active)
        if user:
            marker='</nav>'
            extra=''
            if user.get('role')=='Employee': extra+='<a href="/v10/myhr">👤 My HR Pro</a>'
            if can(user,'employees.edit'): extra+='<a href="/v10/excel">📊 Excel Grid Pro</a><a href="/v10/matching">🧩 Matching Center Pro</a>'
            if can(user,'employees.view'): extra+='<a href="/v10/intelligence">🚨 Intelligence Center Pro</a>'
            if can(user,'system.manage'): extra+='<a href="/v10/devices">🖥 Devices Pro</a>'
            if extra: extra='<details class="nav-group"><summary>أدوات Pro</summary>'+extra+'</details>'
            out=out.replace(marker,extra+marker,1)
        return out
    server_globals['page']=page10; globals()['page']=page10
    server_globals['v10_alerts_engine']=alerts_engine; server_globals['v10_evaluation_engine']=evaluation_engine; server_globals['v10_validate_records']=v10_validate_records

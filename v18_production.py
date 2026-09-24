# HR Enterprise v18 Production Layer
import io, json, uuid
from datetime import datetime
from openpyxl import Workbook, load_workbook

V18_VERSION = "18.0.0"

def install_v18(g):
    H=g['H']; db=g['db']; page=g['page']; now=g['now']; esc=g['esc']
    audit=g.get('audit', lambda *a, **k: None)
    csrf_field=g['csrf_field']; old_get=H.do_GET; old_post=H.do_POST

    def ensure_schema():
        c=db()
        for s in [
            "CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT)",
            "CREATE TABLE IF NOT EXISTS permission_requests(request_id TEXT PRIMARY KEY,emp_code TEXT NOT NULL,request_date TEXT NOT NULL,permission_type TEXT NOT NULL,start_time TEXT,end_time TEXT,duration_minutes INTEGER DEFAULT 0,status TEXT DEFAULT 'قيد المراجعة',requested_by TEXT,approved_by TEXT,approved_at TEXT,notes TEXT,created_at TEXT)",
            "CREATE INDEX IF NOT EXISTS idx_permission_requests_emp_date ON permission_requests(emp_code,request_date)",
            "CREATE INDEX IF NOT EXISTS idx_permission_requests_status ON permission_requests(status)"
        ]:
            try: c.execute(s)
            except Exception: pass
        defaults={
            'policy_permission_normal_max_month':'2','policy_permission_normal_max_minutes':'120',
            'policy_permission_morning_start':'08:00','policy_permission_morning_end':'10:00',
            'policy_permission_evening_start':'20:00','policy_permission_evening_end':'22:00',
            'policy_permission_emergency_enabled':'1','policy_permission_emergency_requires_approval':'1',
            'policy_timezone':'Africa/Cairo','policy_workday_start':'08:00','policy_workday_end':'16:00'
        }
        for k,v in defaults.items():
            try: c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",(k,v))
            except Exception: pass
        c.commit(); c.close()

    def sget(k, default=''):
        try:
            c=db(); r=c.execute("SELECT value FROM settings WHERE key=?",(k,)).fetchone(); c.close()
            return r['value'] if r else default
        except Exception: return default

    def is_admin(u): return bool(u and u.get('role') in ('SuperAdmin','System Admin','admin'))

    def policy_page(self,u,msg=''):
        if not is_admin(u): return self.send('Forbidden',403)
        keys=['policy_permission_normal_max_month','policy_permission_normal_max_minutes','policy_permission_morning_start','policy_permission_morning_end','policy_permission_evening_start','policy_permission_evening_end','policy_permission_emergency_enabled','policy_permission_emergency_requires_approval','policy_timezone','policy_workday_start','policy_workday_end']
        vals={k:sget(k) for k in keys}
        body=f'''<div class="top"><div class="title"><h1>HR Policies</h1><p>قواعد الإجازات والأذونات قابلة للتعديل بدون تعديل الكود.</p></div></div>{msg}
<form method="post" action="/settings/hr-policies"><div class="card">{csrf_field(u)}
<h3>الأذونات</h3><div class="grid">
<label>الاعتيادي / شهر<input name="normal_max_month" type="number" min="0" value="{esc(vals['policy_permission_normal_max_month'])}"></label>
<label>الحد الأقصى بالدقائق<input name="normal_max_minutes" type="number" min="1" value="{esc(vals['policy_permission_normal_max_minutes'])}"></label>
<label>الصباحي من<input name="morning_start" value="{esc(vals['policy_permission_morning_start'])}"></label>
<label>الصباحي إلى<input name="morning_end" value="{esc(vals['policy_permission_morning_end'])}"></label>
<label>المسائي من<input name="evening_start" value="{esc(vals['policy_permission_evening_start'])}"></label>
<label>المسائي إلى<input name="evening_end" value="{esc(vals['policy_permission_evening_end'])}"></label>
<label>إذن الطوارئ<select name="emergency_enabled"><option value="1" {'selected' if vals['policy_permission_emergency_enabled']=='1' else ''}>مفعل</option><option value="0" {'selected' if vals['policy_permission_emergency_enabled']!='1' else ''}>غير مفعل</option></select></label>
<label>اعتماد الطوارئ<select name="emergency_approval"><option value="1" {'selected' if vals['policy_permission_emergency_requires_approval']=='1' else ''}>مطلوب</option><option value="0" {'selected' if vals['policy_permission_emergency_requires_approval']!='1' else ''}>غير مطلوب</option></select></label>
</div><h3>الدوام والتوقيت</h3><div class="grid">
<label>Timezone<input name="timezone" value="{esc(vals['policy_timezone'])}"></label>
<label>بداية الدوام<input name="workday_start" value="{esc(vals['policy_workday_start'])}"></label>
<label>نهاية الدوام<input name="workday_end" value="{esc(vals['policy_workday_end'])}"></label>
</div><div class="actions"><button class="btn ok">حفظ السياسات</button></div></div></form>'''
        self.send(page('HR Policies',body,u,'settings'))

    def policy_save(self,u,f):
        if not is_admin(u): return self.send('Forbidden',403)
        vals={
            'policy_permission_normal_max_month':str(max(0,int(f.get('normal_max_month','2') or 2))),
            'policy_permission_normal_max_minutes':str(max(1,int(f.get('normal_max_minutes','120') or 120))),
            'policy_permission_morning_start':f.get('morning_start','08:00')[:5],
            'policy_permission_morning_end':f.get('morning_end','10:00')[:5],
            'policy_permission_evening_start':f.get('evening_start','20:00')[:5],
            'policy_permission_evening_end':f.get('evening_end','22:00')[:5],
            'policy_permission_emergency_enabled':'1' if f.get('emergency_enabled')=='1' else '0',
            'policy_permission_emergency_requires_approval':'1' if f.get('emergency_approval')=='1' else '0',
            'policy_timezone':f.get('timezone','Africa/Cairo')[:64],
            'policy_workday_start':f.get('workday_start','08:00')[:5],
            'policy_workday_end':f.get('workday_end','16:00')[:5]
        }
        c=db()
        for k,v in vals.items():
            try: c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(k,v))
            except Exception: c.execute("UPDATE settings SET value=? WHERE key=?",(v,k))
        c.commit(); c.close(); audit(u['username'],u['role'],'HR policy update','settings','v18',json.dumps(vals,ensure_ascii=False))
        return policy_page(self,u,'<div class="card"><div class="alert ok">تم حفظ السياسات.</div></div>')

    DATASETS={
        'employees':(['emp_code','name','national_id','phone','email','job','department','location','gender','hire_date','status','basic_salary','allowances','total_salary','notes','employee_group','birth_date','address','qualification','iban','bank_name','bank_branch','unit','contract_date','contract_amount'],'emp_code','employees'),
        'leaves':(['request_no','emp_code','leave_type','start_date','end_date','days','request_date','status','approved_by','approved_at','notes'],'request_no','leaves'),
        'attendance':(['work_date','emp_code','status','check_in','check_out','late_minutes','work_hours','overtime','notes'],'work_date|emp_code','attendance'),
        'permission_requests':(['request_id','emp_code','request_date','permission_type','start_time','end_time','duration_minutes','status','requested_by','approved_by','approved_at','notes'],'request_id','permission_requests')
    }

    def data_center(self,u,msg=''):
        if not u:return self.send('Unauthorized',401)
        rows=''.join(f'<tr><td>{esc(k)}</td><td><a class="btn" href="/data-center/template/{k}">Template</a> <a class="btn" href="/data-center/export/{k}">Export XLSX</a> <a class="btn gray" href="/data-center/import/{k}">Import / Ctrl+V</a></td></tr>' for k in DATASETS)
        body=f'''<div class="top"><div class="title"><h1>Universal Data Center</h1><p>Import / Export / Templates / Clipboard — بدون Internet.</p></div></div>{msg}
<div class="card"><table class="table"><thead><tr><th>Dataset</th><th>Actions</th></tr></thead><tbody>{rows}</tbody></table></div>
<div class="card"><b>Import safety:</b> كل Import يتم Validation ثم Transaction واحدة. إذا فشل commit يتم Rollback ولا يحدث نصف استيراد.</div>'''
        self.send(page('Data Center',body,u,'import'))

    def template(self,u,ds):
        if ds not in DATASETS:return self.send('Not found',404)
        headers=DATASETS[ds][0]; wb=Workbook(); ws=wb.active; ws.title=ds; ws.append(headers); ws.freeze_panes='A2'
        bio=io.BytesIO(); wb.save(bio)
        self.send(bio.getvalue(),200,'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',{'Content-Disposition':f'attachment; filename="{ds}_template.xlsx"','Cache-Control':'no-store'})

    def export_ds(self,u,ds):
        if ds not in DATASETS:return self.send('Not found',404)
        headers,key,table=DATASETS[ds]; c=db(); rows=c.execute(f"SELECT {','.join(headers)} FROM {table} ORDER BY rowid DESC LIMIT 100000").fetchall(); c.close()
        wb=Workbook(); ws=wb.active; ws.title=ds; ws.append(headers)
        for r in rows:ws.append([r[h] for h in headers])
        bio=io.BytesIO(); wb.save(bio)
        self.send(bio.getvalue(),200,'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',{'Content-Disposition':f'attachment; filename="{ds}_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx"','Cache-Control':'no-store'})

    def import_page(self,u,ds,msg=''):
        if ds not in DATASETS:return self.send('Not found',404)
        headers=DATASETS[ds][0]
        body=f'''<div class="top"><div class="title"><h1>Import {esc(ds)}</h1><p>Excel أو Ctrl+V من Excel. يتم Preview/Validation قبل الحفظ.</p></div></div>{msg}
<div class="card"><form method="post" action="/data-center/import/{ds}" enctype="multipart/form-data">{csrf_field(u)}<input type="file" name="file" accept=".xlsx,.csv"><button class="btn">Preview Excel</button></form></div>
<div class="card"><form method="post" action="/data-center/import/{ds}">{csrf_field(u)}<textarea name="paste_data" rows="12" style="width:100%" placeholder="انسخ الخلايا من Excel ثم Ctrl+V هنا"></textarea><button class="btn">Preview Paste</button></form></div>
<div class="card"><b>Columns:</b> {esc(', '.join(headers))}</div>'''
        self.send(page('Import',body,u,'import'))

    def parse_xlsx(ds,raw):
        headers=DATASETS[ds][0]; wb=load_workbook(io.BytesIO(raw),read_only=True,data_only=True); ws=wb.active; it=ws.iter_rows(values_only=True); first=next(it,None)
        if not first:return []
        firstn=[str(x or '').strip() for x in first]; rows=[] if firstn[:len(headers)]==headers else [first]; rows.extend(it)
        return [{h:(r[i] if i<len(r) else '') for i,h in enumerate(headers)} for r in rows if any(str(x or '').strip() for x in r)]

    def parse_paste(ds,text):
        headers=DATASETS[ds][0]; lines=[x for x in text.splitlines() if x.strip()]
        if not lines:return []
        first=lines[0].split('\t'); start=1 if [x.strip() for x in first[:len(headers)]]==headers else 0; out=[]
        for line in lines[start:]:
            cells=line.split('\t'); d={h:(cells[i].strip() if i<len(cells) else '') for i,h in enumerate(headers)}
            if any(d.values()):out.append(d)
        return out

    def validate(ds,rows):
        errors=[]
        for i,r in enumerate(rows,2):
            if ds=='employees' and not str(r.get('emp_code') or '').strip():errors.append((i,'emp_code','Employee Code is required'))
            elif ds=='leaves' and (not r.get('request_no') or not r.get('emp_code') or not r.get('start_date')):errors.append((i,'leave','request_no, emp_code and start_date are required'))
            elif ds=='attendance' and (not r.get('work_date') or not r.get('emp_code')):errors.append((i,'attendance','work_date and emp_code are required'))
            elif ds=='permission_requests' and (not r.get('emp_code') or not r.get('request_date') or not r.get('permission_type')):errors.append((i,'permission','emp_code, request_date and permission_type are required'))
        return errors

    def commit_rows(u,ds,rows):
        headers,key,table=DATASETS[ds]; c=db(); new=upd=0
        try:
            for r in rows:
                if ds=='permission_requests' and not r.get('request_id'):r['request_id']=uuid.uuid4().hex
                wc=key.split('|'); where=' AND '.join(f'{x}=?' for x in wc); vals=[r.get(x,'') for x in wc]
                old=c.execute(f"SELECT 1 FROM {table} WHERE {where} LIMIT 1",vals).fetchone()
                if old:
                    sets=[h for h in headers if h not in wc]
                    if sets:c.execute(f"UPDATE {table} SET {','.join(h+'=?' for h in sets)} WHERE {where}",[r.get(h,'') for h in sets]+vals);upd+=1
                else:
                    c.execute(f"INSERT INTO {table} ({','.join(headers)}) VALUES ({','.join('?' for _ in headers)})",[r.get(h,'') for h in headers]);new+=1
            c.commit()
        except Exception:
            c.rollback();c.close();raise
        c.close();audit(u['username'],u['role'],'Data import',ds,str(len(rows)),f'new={new},updated={upd}');return new,upd

    def import_post(u,ds,f,raw):
        if ds not in DATASETS:return self.send('Not found',404)
        try:rows=parse_paste(ds,f.get('paste_data','')) if f.get('paste_data') else parse_xlsx(ds,raw)
        except Exception as e:return import_page(self,u,ds,f'<div class="card"><div class="alert">Excel غير صالح: {esc(str(e))}</div></div>')
        errs=validate(ds,rows)
        if errs:
            eh=''.join(f'<tr><td>{i}</td><td>{esc(a)}</td><td>{esc(b)}</td></tr>' for i,a,b in errs[:200])
            return import_page(self,u,ds,f'<div class="card"><h3>Validation Errors: {len(errs)}</h3><table class="table"><tr><th>Row</th><th>Field</th><th>Error</th></tr>{eh}</table><p>لم يتم استيراد أي صف.</p></div>')
        try:new,upd=commit_rows(u,ds,rows)
        except Exception as e:return import_page(self,u,ds,f'<div class="card"><div class="alert">Transaction rolled back: {esc(str(e))}</div></div>')
        return data_center(self,u,f'<div class="card"><div class="alert ok">Import successful — {len(rows)} rows, New {new}, Updated {upd}.</div></div>')

    def permission_page(self,u,msg=''):
        body=f'''<div class="top"><div class="title"><h1>Permission Requests</h1><p>اعتيادي، صباحي، مسائي، طوارئ — القواعد من Settings.</p></div></div>{msg}
<div class="card"><form method="post" action="/permission-requests/save">{csrf_field(u)}<div class="grid">
<label>Employee Code<input name="emp_code" required></label><label>Date<input type="date" name="request_date" required></label>
<label>Type<select name="permission_type"><option>اعتيادي</option><option>صباحي</option><option>مسائي</option><option>طوارئ</option></select></label>
<label>From<input type="time" name="start_time"></label><label>To<input type="time" name="end_time"></label><label>Notes<input name="notes"></label>
</div><button class="btn ok">Submit</button></form></div>
<div class="card"><a class="btn" href="/data-center/export/permission_requests">Export Excel</a> <a class="btn gray" href="/data-center/import/permission_requests">Import Excel / Ctrl+V</a></div>'''
        self.send(page('Permission Requests',body,u,'attendance'))

    def permission_save(u,f):
        if f.get('_csrf')!=u.get('csrf'):return self.send('Invalid CSRF',403)
        emp=f.get('emp_code','').strip();typ=f.get('permission_type','').strip();d=f.get('request_date','').strip();st=f.get('start_time','');et=f.get('end_time','')
        if not emp or not d or not typ:return permission_page(self,u,'<div class="card"><div class="alert">بيانات ناقصة.</div></div>')
        if typ=='طوارئ' and sget('policy_permission_emergency_enabled','1')!='1':return permission_page(self,u,'<div class="card"><div class="alert">إذن الطوارئ غير مفعل.</div></div>')
        dur=0
        if st and et:
            try:a,b=[int(x.split(':')[0])*60+int(x.split(':')[1]) for x in (st,et)]
            except Exception:return permission_page(self,u,'<div class="card"><div class="alert">وقت غير صحيح.</div></div>')
            if b<=a:return permission_page(self,u,'<div class="card"><div class="alert">الفترة الزمنية غير صحيحة.</div></div>')
            dur=b-a
        if typ=='اعتيادي':
            if dur>int(sget('policy_permission_normal_max_minutes','120')):return permission_page(self,u,'<div class="card"><div class="alert">المدة تتجاوز الحد المسموح.</div></div>')
            c=db();r=c.execute("SELECT COUNT(*) n FROM permission_requests WHERE emp_code=? AND substr(request_date,1,7)=substr(?,1,7) AND permission_type='اعتيادي' AND status<>'مرفوض'",(emp,d)).fetchone();c.close()
            if int(r['n'])>=int(sget('policy_permission_normal_max_month','2')):return permission_page(self,u,'<div class="card"><div class="alert">تم تجاوز عدد الأذونات الاعتيادية لهذا الشهر.</div></div>')
        status='معتمد' if typ=='طوارئ' and sget('policy_permission_emergency_requires_approval','1')!='1' else 'قيد المراجعة'
        rid=uuid.uuid4().hex;c=db();c.execute("INSERT INTO permission_requests(request_id,emp_code,request_date,permission_type,start_time,end_time,duration_minutes,status,requested_by,created_at,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(rid,emp,d,typ,st,et,dur,status,u['username'],now(),f.get('notes','')[:500]));c.commit();c.close()
        audit(u['username'],u['role'],'Permission request','permission_requests',rid,f'{typ} {emp} {d}')
        return permission_page(self,u,'<div class="card"><div class="alert ok">تم تسجيل الإذن.</div></div>')

    def admin_reset_page(self,u,msg=''):
        if not is_admin(u):return self.send('Forbidden',403)
        body=f'''<div class="top"><div class="title"><h1>Admin Password Recovery</h1><p>لا يوجد Random Password. يمكن ضبط كلمة مرور admin يدويًا.</p></div></div>{msg}
<div class="card"><form method="post" action="/admin/password-reset">{csrf_field(u)}<label>New password<input type="password" name="new_password" minlength="10"></label><p>اتركه فارغًا لاستخدام Admin@12345.</p><button class="btn ok">Reset admin password</button></form></div>'''
        self.send(page('Admin Password Recovery',body,u,'settings'))

    def admin_reset(u,f):
        if not is_admin(u):return self.send('Forbidden',403)
        new=(f.get('new_password') or '').strip() or 'Admin@12345'
        if len(new)<10:return admin_reset_page(self,u,'<div class="card"><div class="alert">الحد الأدنى 10 أحرف.</div></div>')
        c=db();c.execute("UPDATE users SET password_hash=?,must_change_password=0 WHERE username='admin'",(g['hashpw'](new),));c.commit();c.close()
        audit(u['username'],u['role'],'Admin password reset','users','admin','manual reset')
        return admin_reset_page(self,u,'<div class="card"><div class="alert ok">تم تغيير كلمة مرور admin. لا يوجد Random Password.</div></div>')

    def get(self):
        p=g['urlparse'](self.path).path
        if p=='/settings/hr-policies':
            u=self.require();return policy_page(self,u) if u else None
        if p=='/data-center':
            u=self.require();return data_center(self,u) if u else None
        if p.startswith('/data-center/template/'):
            u=self.require();return template(self,u,p.rsplit('/',1)[-1]) if u else None
        if p.startswith('/data-center/export/'):
            u=self.require();return export_ds(self,u,p.rsplit('/',1)[-1]) if u else None
        if p.startswith('/data-center/import/'):
            u=self.require();return import_page(self,u,p.rsplit('/',1)[-1]) if u else None
        if p=='/permission-requests':
            u=self.require();return permission_page(self,u) if u else None
        if p=='/admin/password-reset':
            u=self.require();return admin_reset_page(self,u) if u else None
        return old_get(self)

    def post(self):
        p=g['urlparse'](self.path).path
        if p=='/settings/hr-policies' or p=='/admin/password-reset' or p=='/permission-requests/save' or p.startswith('/data-center/import/'):
            u=self.require()
            if not u:return
            if u.get('must_change_password') and p!='/password':return self.redirect('/password')
            ctype=self.headers.get('Content-Type','').lower()
            if ctype.startswith('multipart/form-data'):
                f,file_part=self.parse_upload();raw=file_part[1] if isinstance(file_part,tuple) and len(file_part)>1 else b''
            else:f=self.form();raw=b''
            if f.get('_csrf')!=u.get('csrf'):return self.send('Invalid CSRF',403)
            if p=='/settings/hr-policies':return policy_save(self,u,f)
            if p=='/admin/password-reset':return admin_reset(u,f)
            if p=='/permission-requests/save':return permission_save(self,u,f)
            return import_post(self,u,p.rsplit('/',1)[-1],f,raw)
        return old_post(self)

    H.do_GET=get;H.do_POST=post;g['V18_VERSION']=V18_VERSION;ensure_schema()

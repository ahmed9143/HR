import os, io, json, csv, types
from urllib.parse import quote, urlparse, parse_qs
from datetime import date, timedelta


def install(g):
    H=g['H']; db=g['db']; page=g['page']; esc=g['esc']; csrf_field=g['csrf_field']; can=g['can']; now=g['now']
    emp_allowed=g['emp_allowed']; visible_sql=g['visible_employee_sql']; DATA=g['DATA']

    def is_admin(u):
        return bool(u and u.get('role') in ('Admin','SuperAdmin'))

    # ---------------- GET scope hardening ----------------
    old_get=H.do_GET
    def get(self):
        p=urlparse(self.path).path
        custom = (p.startswith('/employee/edit/') or p.startswith('/employee/photo/') or p.startswith('/qr/image/') or p=='/id-cards' or p=='/contracts' or p=='/training' or p=='/hr-inbox' or p=='/assets' or p.startswith('/employee/profile/'))
        if not custom:
            return old_get(self)
        u=self.require()
        if not u:
            return None
        # Employee edit must authorize before loading the employee row.
        if p.startswith('/employee/edit/'):
            code=p.split('/employee/edit/',1)[1]
            if not emp_allowed(u,code): return self.forbid(u)
            return old_get(self)
        # Direct media endpoints are data endpoints too: scope them before reading bytes.
        if p.startswith('/employee/photo/'):
            code=p.split('/employee/photo/',1)[1]
            if not can(u,'employees.view') or not emp_allowed(u,code): return self.forbid(u)
            c=db(); r=c.execute("SELECT id,storage_path,file_name,data FROM documents WHERE emp_code=? AND category='صورة' AND status='current' ORDER BY id DESC LIMIT 1",(code,)).fetchone(); c.close()
            if not r: return self.send(b'',404,'image/png')
            try:
                data=None
                if r['storage_path']:
                    data=g['secure_file_bytes'](r['storage_path'])
                if data is None and r['data'] is not None: data=r['data']
                if not data: return self.send(b'',404,'image/png')
                return self.send(data,200,g.get('mimetypes').guess_type(r['file_name'])[0] if g.get('mimetypes') else 'image/jpeg',{'Cache-Control':'private,max-age=86400'})
            except Exception:
                return self.send(b'',404,'image/png')
        # QR image is scoped. Generation itself is admin-only below.
        if p.startswith('/qr/image/'):
            code=p.split('/qr/image/',1)[1]
            if not can(u,'employees.view') or not emp_allowed(u,code): return self.forbid(u)
            return old_get(self)
        # Bulk ID cards must never fall back to an unscoped first-50 query.
        if p=='/id-cards':
            return bulk_id_cards(self,u)
        # Contracts/training are rewritten with scope-aware reads and simpler UX.
        if p=='/contracts': return contracts_page(self,u)
        if p=='/training': return training_page(self,u)
        if p=='/hr-inbox': return inbox_page(self,u)
        if p=='/assets': return assets_page(self,u)
        if p.startswith('/employee/profile/'):
            code=p.split('/employee/profile/',1)[1]
            if not emp_allowed(u,code): return self.forbid(u)
            return old_get(self)
        return old_get(self)
    H.do_GET=get

    # ---------------- POST hardening ----------------
    old_post=H.do_POST
    def post(self):
        p=urlparse(self.path).path
        if p in ('/qr/generate','/qr/regenerate','/qr/revoke','/qr/generate-all','/employee/photo/upload'):
            u=self.require()
            if not u: return None
            if not is_admin(u): return self.forbid(u)
            return old_post(self)
        if p in ('/contracts/save','/contracts/action','/training/program/save','/training/enroll','/assets/save','/assets/action'):
            u=self.require()
            if not u: return None
            if p.startswith('/training') and not can(u,'employees.edit'):
                return self.forbid(u)
            if p.startswith('/contracts') and not can(u,'employees.edit'):
                return self.forbid(u)
            if p.startswith('/assets') and not can(u,'employees.edit'):
                return self.forbid(u)
            # Explicit scope for all employee-targeting mutations, even if an older handler
            # is later changed or bypassed by another feature wrapper.
            ctype=self.headers.get('Content-Type','').lower()
            f=self.form() if not ctype.startswith('multipart/form-data') else self.parse_upload()[0]
            if f.get('_csrf')!=u.get('csrf'):
                return self.send(page('Security','<div class="card"><div class="alert">Invalid CSRF.</div></div>',u),403)
            if p in ('/contracts/save','/training/enroll','/assets/save'):
                emp=f.get('emp_code','').strip()
                if not emp or not emp_allowed(u,emp): return self.forbid(u)
            if p=='/contracts/action':
                try: cid=int(f.get('id') or 0)
                except Exception: cid=0
                c=db(); r=c.execute('SELECT emp_code FROM contracts WHERE id=?',(cid,)).fetchone(); c.close()
                if not r or not emp_allowed(u,r['emp_code']): return self.forbid(u)
            if p=='/assets/action':
                try: aid=int(f.get('id') or 0)
                except Exception: aid=0
                c=db(); r=c.execute('SELECT emp_code FROM employee_assets WHERE id=?',(aid,)).fetchone(); c.close()
                if not r or not emp_allowed(u,r['emp_code']): return self.forbid(u)
            return old_post(self)
        return old_post(self)
    H.do_POST=post

    # ---------------- Scope-aware Contracts ----------------
    def contracts_page(self,u):
        if not can(u,'employees.view'): return self.forbid(u)
        cond,args=visible_sql(u,'e')
        c=db()
        rows=c.execute('SELECT ct.*,e.name,e.department,e.unit FROM contracts ct JOIN employees e ON e.emp_code=ct.emp_code WHERE 1=1'+cond+' ORDER BY CASE WHEN ct.end_date IS NULL OR ct.end_date="" THEN 1 ELSE 0 END, ct.end_date ASC,ct.id DESC LIMIT 500',args).fetchall()
        emps=c.execute('SELECT e.emp_code,e.name FROM employees e WHERE e.status<>"مؤرشف"'+cond.replace('e.','e.')+' ORDER BY e.name',args).fetchall()
        c.close()
        today=date.today().isoformat(); soon=(date.today()+timedelta(days=30)).isoformat()
        active=sum(1 for r in rows if (r['status'] or '').lower() in ('active','renewed') and (not r['end_date'] or r['end_date']>=today))
        expiring=sum(1 for r in rows if r['end_date'] and today<=r['end_date']<=soon and (r['status'] or '').lower() not in ('terminated','expired'))
        expired=sum(1 for r in rows if r['end_date'] and r['end_date']<today and (r['status'] or '').lower() not in ('terminated',))
        missing=max(0,len(emps)-len({r['emp_code'] for r in rows}))
        def badge(st,end):
            if st=='terminated': return '<span class="badge b-bad">Terminated</span>'
            if end and end<today: return '<span class="badge b-bad">Expired</span>'
            if end and end<=soon: return '<span class="badge b-warn">Expiring</span>'
            return '<span class="badge b-ok">Active</span>'
        trs=''.join(f'<tr><td>{esc(r["contract_no"] or r["id"])}</td><td><a href="/employee/profile/{quote(r["emp_code"])}">{esc(r["emp_code"])} · {esc(r["name"])}</a></td><td>{esc(r["start_date"] or "—")}</td><td>{esc(r["end_date"] or "—")}</td><td>{badge((r["status"] or "").lower(),r["end_date"])}</td><td>{float(r["amount"] or 0):g}</td><td>{("<form method=\"post\" action=\"/contracts/action\" style=\"display:inline\">"+csrf_field(u)+f'<input type="hidden" name="id" value="{r["id"]}"><input type="hidden" name="action" value="terminate"><button class="btn bad">إنهاء</button></form>') if can(u,'employees.edit') else ''}</td></tr>' for r in rows)
        opts=''.join(f'<option value="{esc(e["emp_code"])}">{esc(e["emp_code"])} — {esc(e["name"])}</option>' for e in emps)
        form=f'''<div class="card"><h3>➕ إضافة عقد</h3><form method="post" action="/contracts/save" class="form">{csrf_field(u)}<div class="field"><label>الموظف</label><select name="emp_code" required>{opts}</select></div><div class="field"><label>رقم العقد</label><input name="contract_no"></div><div class="field"><label>النوع</label><input name="contract_type" value="employment"></div><div class="field"><label>من</label><input type="date" name="start_date"></div><div class="field"><label>إلى</label><input type="date" name="end_date"></div><div class="field"><label>المبلغ</label><input type="number" step="0.01" name="amount"></div><div class="field"><label>الحالة</label><select name="status"><option>active</option><option>renewed</option><option>terminated</option><option>expired</option></select></div><div class="field full"><label>ملاحظات</label><textarea name="notes"></textarea></div><button class="btn">حفظ العقد</button></form></div>''' if can(u,'employees.edit') else ''
        body=f'''<div class="top"><div class="title"><h1>📑 العقود</h1><p>عرض وإدارة العقود داخل نطاق صلاحيتك فقط.</p></div></div><div class="grid g4 stat-row"><div class="card metric"><div class="label">سارية</div><div class="value">{active}</div></div><div class="card metric"><div class="label">تنتهي خلال 30 يوم</div><div class="value">{expiring}</div></div><div class="card metric"><div class="label">منتهية</div><div class="value">{expired}</div></div><div class="card metric"><div class="label">بدون عقد</div><div class="value">{missing}</div></div></div>{form}<div class="card" style="margin-top:16px"><div class="table-wrap"><table class="table"><thead><tr><th>رقم</th><th>الموظف</th><th>من</th><th>إلى</th><th>الحالة</th><th>المبلغ</th><th></th></tr></thead><tbody>{trs or '<tr><td colspan="7">لا توجد عقود</td></tr>'}</tbody></table></div></div>'''
        self.send(page('العقود',body,u,'enterprise'))

    # ---------------- Scope-aware Training ----------------
    def training_page(self,u):
        if not can(u,'employees.view'): return self.forbid(u)
        cond,args=visible_sql(u,'e')
        c=db(); programs=c.execute('SELECT * FROM training_programs WHERE active=1 ORDER BY name').fetchall()
        emps=c.execute('SELECT e.emp_code,e.name FROM employees e WHERE e.status<>"مؤرشف"'+cond+' ORDER BY e.name',args).fetchall()
        rows=c.execute('SELECT te.*,tp.name program_name,e.name,e.department FROM training_enrollments te LEFT JOIN training_programs tp ON tp.id=te.program_id JOIN employees e ON e.emp_code=te.emp_code WHERE 1=1'+cond+' ORDER BY te.id DESC LIMIT 500',args).fetchall(); c.close()
        opts=''.join(f'<option value="{p["id"]}">{esc(p["name"])}</option>' for p in programs); eopts=''.join(f'<option value="{esc(e["emp_code"])}">{esc(e["emp_code"])} — {esc(e["name"])}</option>' for e in emps)
        trs=''.join(f'<tr><td><a href="/employee/profile/{quote(r["emp_code"])}">{esc(r["emp_code"])} · {esc(r["name"])}</a></td><td>{esc(r["program_name"] or "")}</td><td>{esc(r["start_date"] or "—")}</td><td>{esc(r["completion_date"] or "—")}</td><td>{esc(r["certificate_expiry"] or "—")}</td><td>{esc(r["status"] or "")}</td></tr>' for r in rows)
        form=f'''<div class="grid g2"><div class="card"><h3>🎓 برنامج جديد</h3><form method="post" action="/training/program/save">{csrf_field(u)}<div class="field"><label>اسم البرنامج</label><input name="name" required></div><div class="field"><label>الجهة</label><input name="provider"></div><div class="field full"><label>الوصف</label><textarea name="description"></textarea></div><button class="btn">حفظ البرنامج</button></form></div><div class="card"><h3>👤 تسجيل موظف</h3><form method="post" action="/training/enroll">{csrf_field(u)}<div class="field"><label>البرنامج</label><select name="program_id" required>{opts}</select></div><div class="field"><label>الموظف</label><select name="emp_code" required>{eopts}</select></div><div class="field"><label>البداية</label><input type="date" name="start_date"></div><div class="field"><label>النهاية</label><input type="date" name="end_date"></div><div class="field"><label>إتمام</label><input type="date" name="completion_date"></div><div class="field"><label>انتهاء الشهادة</label><input type="date" name="certificate_expiry"></div><div class="field"><label>الحالة</label><select name="status"><option>enrolled</option><option>completed</option><option>failed</option><option>cancelled</option></select></div><button class="btn">حفظ التسجيل</button></form></div></div>''' if can(u,'employees.edit') else ''
        body=f'''<div class="top"><div class="title"><h1>🎓 التدريب</h1><p>البرامج والتسجيلات والشهادات داخل نطاق صلاحيتك فقط.</p></div></div>{form}<div class="card" style="margin-top:16px"><div class="table-wrap"><table class="table"><thead><tr><th>الموظف</th><th>البرنامج</th><th>البداية</th><th>الإتمام</th><th>انتهاء الشهادة</th><th>الحالة</th></tr></thead><tbody>{trs or '<tr><td colspan="6">لا توجد سجلات تدريب</td></tr>'}</tbody></table></div></div>'''
        self.send(page('التدريب',body,u,'enterprise'))

    # ---------------- Bulk ID cards, scope-aware and non-hanging ----------------
    def bulk_id_cards(self,u):
        if not can(u,'employees.view'): return self.forbid(u)
        qs=parse_qs(urlparse(self.path).query); raw=qs.get('codes',[''])[0]
        requested=[x.strip() for x in raw.split(',') if x.strip()][:50] if raw else []
        if requested:
            codes=[x for x in requested if emp_allowed(u,x)]
        else:
            cond,args=visible_sql(u,'e'); c=db(); codes=[r['emp_code'] for r in c.execute('SELECT e.emp_code FROM employees e WHERE e.status<>"مؤرشف"'+cond+' ORDER BY e.name LIMIT 50',args).fetchall()]; c.close()
        c=db(); missing=sum(1 for r in c.execute("SELECT e.emp_code FROM employees e WHERE e.status<>'مؤرشف' AND NOT EXISTS (SELECT 1 FROM qr_identities q WHERE q.emp_code=e.emp_code AND q.status='active')").fetchall() if emp_allowed(u,r['emp_code'])); c.close()
        gen_btn=f'<button class="btn ok" type="button" onclick="genAllQr(this)">⚡ توليد QR للموظفين داخل النطاق ({missing} بدون QR)</button>' if missing and is_admin(u) else ''
        links=''.join(f'<div class="bulk-card"><div class="bulk-head"><a href="/employee/profile/{quote(code)}">{esc(code)}</a><a class="btn gray" href="/id-card/{quote(code)}">فتح البطاقة</a></div><iframe loading="lazy" src="/id-card/{quote(code)}" title="ID Card {esc(code)}"></iframe></div>' for code in codes)
        body=f'''<div class="top no-print"><div class="title"><h1>🪪 بطاقات الموظفين</h1><p>{len(codes)} بطاقة · البطاقات تُحمّل بشكل تدريجي بدل تجميد الصفحة.</p></div><div class="actions">{gen_btn}<button class="btn" onclick="window.print()">🖨 طباعة</button></div></div><div class="bulk-grid">{links or '<div class="card">لا توجد بطاقات ضمن نطاقك.</div>'}</div><style>.bulk-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(430px,1fr));gap:16px}}.bulk-card{{background:#fff;border:1px solid #e4e7ec;border-radius:18px;overflow:hidden;box-shadow:0 8px 25px rgba(16,24,40,.06)}}.bulk-head{{display:flex;justify-content:space-between;align-items:center;padding:12px 14px;background:#f8fafc}}.bulk-card iframe{{width:100%;height:430px;border:0;display:block}}@media print{{.bulk-grid{{display:block}}.bulk-card{{break-inside:avoid;margin-bottom:18px}}.bulk-card iframe{{height:520px}}}}</style><script>async function genAllQr(btn){{btn.disabled=true;var offset=0,total=0,created=0;try{{while(true){{btn.textContent='جاري التوليد… '+(total?Math.min(100,Math.round(offset*100/total)):0)+'%';var fd=new FormData();fd.append('_csrf','{esc(u.get("csrf",""))}');var r=await fetch('/qr/generate-all?offset='+offset+'&limit=8',{{method:'POST',body:fd}});if(!r.ok)throw new Error('HTTP '+r.status);var d=await r.json();offset=d.processed;total=d.total;created+=d.created;if(d.done)break;}}alert('تم توليد '+created+' كود QR.');location.reload();}}catch(e){{alert('فشل التوليد بعد '+created+' كود. راجع سجل الأخطاء.');btn.disabled=false;btn.textContent='إعادة المحاولة';}}}}</script>'''
        self.send(page('بطاقات الموظفين',body,u,'employees'))

    # ---------------- Employee assets ----------------
    def ensure_assets():
        c=db(); c.execute('''CREATE TABLE IF NOT EXISTS employee_assets(id INTEGER PRIMARY KEY,emp_code TEXT NOT NULL,asset_type TEXT NOT NULL,asset_no TEXT,description TEXT,issued_date TEXT,returned_date TEXT,status TEXT DEFAULT 'issued',notes TEXT,created_by TEXT,created_at TEXT,updated_at TEXT)'''); c.execute('CREATE INDEX IF NOT EXISTS idx_employee_assets_emp ON employee_assets(emp_code,status)'); c.commit(); c.close()
    ensure_assets()

    def assets_page(self,u):
        if not can(u,'employees.view'): return self.forbid(u)
        cond,args=visible_sql(u,'e'); c=db(); rows=c.execute('SELECT a.*,e.name FROM employee_assets a JOIN employees e ON e.emp_code=a.emp_code WHERE 1=1'+cond.replace('e.','e.')+' ORDER BY a.id DESC LIMIT 500',args).fetchall(); emps=c.execute('SELECT e.emp_code,e.name FROM employees e WHERE e.status<>"مؤرشف"'+cond+' ORDER BY e.name',args).fetchall(); c.close()
        eopts=''.join(f'<option value="{esc(e["emp_code"])}">{esc(e["emp_code"])} — {esc(e["name"])}</option>' for e in emps)
        trs=''.join(f'<tr><td><a href="/employee/profile/{quote(r["emp_code"])}">{esc(r["emp_code"])} · {esc(r["name"])}</a></td><td>{esc(r["asset_type"])}</td><td>{esc(r["asset_no"] or "—")}</td><td>{esc(r["description"] or "—")}</td><td>{esc(r["issued_date"] or "—")}</td><td>{esc(r["returned_date"] or "—")}</td><td>{"<span class=\"badge b-ok\">مسلمة</span>" if r["status"]=="issued" else "<span class=\"badge b-gray\">مستردة</span>"}</td><td>{(f'<form method="post" action="/assets/action">{csrf_field(u)}<input type="hidden" name="id" value="{r["id"]}"><input type="hidden" name="action" value="return"><button class="btn gray">استرداد</button></form>') if can(u,'employees.edit') and r['status']=='issued' else ''}</td></tr>' for r in rows)
        form=f'''<div class="card"><h3>📦 تسجيل عهدة</h3><form method="post" action="/assets/save" class="form">{csrf_field(u)}<div class="field"><label>الموظف</label><select name="emp_code" required>{eopts}</select></div><div class="field"><label>نوع العهدة</label><select name="asset_type"><option>Laptop</option><option>Mobile</option><option>SIM</option><option>Keys</option><option>ID Card</option><option>Tools</option><option>Other</option></select></div><div class="field"><label>رقم الأصل / Serial</label><input name="asset_no"></div><div class="field"><label>الوصف</label><input name="description"></div><div class="field"><label>تاريخ التسليم</label><input type="date" name="issued_date" value="{date.today().isoformat()}"></div><div class="field full"><label>ملاحظات</label><textarea name="notes"></textarea></div><button class="btn">حفظ العهدة</button></form></div>''' if can(u,'employees.edit') else ''
        body=f'''<div class="top"><div class="title"><h1>📦 عهد الموظفين</h1><p>تسليم واسترداد العهد مع ربطها بملف الموظف.</p></div></div>{form}<div class="card" style="margin-top:16px"><div class="table-wrap"><table class="table"><thead><tr><th>الموظف</th><th>النوع</th><th>Serial</th><th>الوصف</th><th>التسليم</th><th>الاسترداد</th><th>الحالة</th><th></th></tr></thead><tbody>{trs or '<tr><td colspan="8">لا توجد عهد</td></tr>'}</tbody></table></div></div>'''
        self.send(page('عهد الموظفين',body,u,'employees'))

    # ---------------- HR Inbox ----------------
    def inbox_page(self,u):
        if u.get('role') not in ('Manager','HR','Admin','SuperAdmin') and not can(u,'employees.view'): return self.forbid(u)
        cond,args=visible_sql(u,'e'); c=db()
        pending_leaves=c.execute("SELECT l.request_no,l.emp_code,e.name,l.start_date,l.end_date FROM leaves l JOIN employees e ON e.emp_code=l.emp_code WHERE l.status IN ('pending','معلق','submitted')"+cond.replace('e.','e.')+" ORDER BY l.id DESC LIMIT 20",args).fetchall() if self._table_exists(c,'leaves') else []
        expiring_docs=c.execute("SELECT d.emp_code,e.name,d.file_name,d.expiry_date FROM documents d JOIN employees e ON e.emp_code=d.emp_code WHERE d.status='current' AND d.expiry_date IS NOT NULL AND d.expiry_date<>'' AND d.expiry_date<=date('now','+30 day') AND d.expiry_date>=date('now')"+cond.replace('e.','e.')+" ORDER BY d.expiry_date LIMIT 20",args).fetchall()
        contracts=c.execute("SELECT ct.emp_code,e.name,ct.end_date FROM contracts ct JOIN employees e ON e.emp_code=ct.emp_code WHERE ct.end_date IS NOT NULL AND ct.end_date<>'' AND ct.end_date<=date('now','+30 day') AND ct.end_date>=date('now')"+cond.replace('e.','e.')+" ORDER BY ct.end_date LIMIT 20",args).fetchall()
        missing_contracts=c.execute("SELECT e.emp_code,e.name FROM employees e LEFT JOIN contracts ct ON ct.emp_code=e.emp_code AND ct.status NOT IN ('terminated','expired') WHERE e.status<>\"مؤرشف\" AND ct.id IS NULL"+cond+" ORDER BY e.name LIMIT 20",args).fetchall()
        c.close()
        def rows(items,kind):
            if not items:return '<div class="empty">لا يوجد شيء يحتاج إجراء.</div>'
            out=[]
            for r in items:
                if kind=='leave': label=f'إجازة {r["request_no"] or ""}'; code=r['emp_code']; sub=f'{r["start_date"] or ""} → {r["end_date"] or ""}'
                elif kind=='doc': label=f'مستند: {r["file_name"]}'; code=r['emp_code']; sub=f'ينتهي {r["expiry_date"]}'
                elif kind=='contract': label='عقد قريب الانتهاء'; code=r['emp_code']; sub=f'ينتهي {r["end_date"]}'
                else: label='موظف بدون عقد'; code=r['emp_code']; sub='يحتاج إنشاء عقد'
                out.append(f'<div class="inbox-item"><div><b>{esc(label)}</b><div class="sub">{esc(r["name"])} · {esc(sub)}</div></div><a class="btn gray" href="/employee/profile/{quote(code)}">فتح</a></div>')
            return ''.join(out)
        sections=[('🟠 إجازات تنتظر الإجراء',pending_leaves,'leave'),('🔴 مستندات تنتهي خلال 30 يوم',expiring_docs,'doc'),('🟡 عقود تنتهي خلال 30 يوم',contracts,'contract'),('⚪ موظفون بدون عقد',missing_contracts,'missing')]
        body=''.join(f'<div class="card inbox-card"><div class="top"><h3>{title}</h3><span class="badge b-blue">{len(items)}</span></div>{rows(items,kind)}</div>' for title,items,kind in sections)
        body=f'''<div class="top"><div class="title"><h1>📥 مركز إجراءات HR</h1><p>كل الأشياء التي تحتاج متابعة في مكان واحد.</p></div></div><div class="inbox-grid">{body}</div><style>.inbox-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:16px}}.inbox-card{{min-height:160px}}.inbox-item{{display:flex;justify-content:space-between;gap:12px;align-items:center;padding:12px 0;border-top:1px solid #eef2f6}}.empty{{color:#667085;padding:14px 0}}.sub{{color:#667085;font-size:13px;margin-top:4px}}</style>'''
        self.send(page('مركز إجراءات HR',body,u,'dashboard'))

    def _table_exists(self,c,name):
        return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone())
    H._table_exists=_table_exists

    # ---------------- Profile security + profile UX ----------------
    old_profile=H.employee_profile
    def profile(self,u,code):
        if not emp_allowed(u,code): return self.forbid(u)
        captured=[]; original=self.send
        def cap(body,status=200,ctype='text/html; charset=utf-8',headers=None): captured.append((body,status,ctype,headers))
        self.send=cap
        try: old_profile(self,u,code)
        finally: self.send=original
        if not captured: return
        body,status,ctype,headers=captured[0]
        if status!=200 or 'text/html' not in ctype: return original(body,status,ctype,headers)
        if isinstance(body,bytes): body=body.decode('utf-8','replace')
        c=db(); assets=c.execute('SELECT * FROM employee_assets WHERE emp_code=? ORDER BY CASE WHEN status="issued" THEN 0 ELSE 1 END,id DESC LIMIT 50',(code,)).fetchall(); c.close()
        asset_rows=''.join(f'<tr><td>{esc(a["asset_type"])}</td><td>{esc(a["asset_no"] or "—")}</td><td>{esc(a["description"] or "—")}</td><td>{esc(a["issued_date"] or "—")}</td><td>{esc(a["returned_date"] or "—")}</td><td>{"🟢 مسلمة" if a["status"]=="issued" else "⚪ مستردة"}</td></tr>' for a in assets)
        actions=''.join([f'<a class="btn" href="#documents">📄 المستندات</a>',f'<a class="btn gray" href="#attendance">⏰ الحضور</a>',f'<a class="btn gray" href="#leaves">🏖 الإجازات</a>',f'<a class="btn gray" href="#payroll">💰 المرتب</a>',f'<a class="btn gray" href="#assets">📦 العهد</a>'])
        if is_admin(u): actions += f'<a class="btn gray" href="/id-card/{quote(code)}">🪪 بطاقة</a>'
        asset_card=f'<div id="assets" class="card" style="margin-top:16px"><div class="top"><h3>📦 عهد الموظف</h3><a class="btn gray" href="/assets">إدارة العهد</a></div><div class="table-wrap"><table class="table"><thead><tr><th>النوع</th><th>Serial</th><th>الوصف</th><th>التسليم</th><th>الاسترداد</th><th>الحالة</th></tr></thead><tbody>{asset_rows or "<tr><td colspan=\"6\">لا توجد عهد مسجلة</td></tr>"}</tbody></table></div></div>'
        marker='<div class="card no-print" style="position:sticky;top:8px;z-index:5;margin-top:16px"><div class="actions">'
        if marker in body:
            body=body.replace(marker,marker+actions,1)
        timeline_marker='<div id="timeline" class="card" style="margin-top:16px">'
        if timeline_marker in body: body=body.replace(timeline_marker,asset_card+timeline_marker,1)
        css='''<style>.profile-hero{display:grid!important;grid-template-columns:150px minmax(0,1fr) 190px;gap:22px;align-items:center;overflow:hidden}.profile-hero .ph-photo-wrap{width:150px!important;height:180px!important}.profile-hero .ph-photo,.profile-hero .ph-photo-empty{width:150px!important;height:180px!important}.profile-hero .ph-qr{min-width:170px!important;display:flex;flex-direction:column;align-items:center;gap:8px}.profile-hero .ph-qr img{width:145px!important;height:145px!important;object-fit:contain;background:#fff;padding:8px;border-radius:14px;border:1px solid #e4e7ec}.profile-hero .qr-actions{display:flex;flex-wrap:wrap;gap:6px;justify-content:center}.profile-hero .ph-actions{display:flex;flex-wrap:wrap;gap:7px}@media(max-width:900px){.profile-hero{grid-template-columns:1fr!important;text-align:center}.profile-hero .ph-photo-wrap,.profile-hero .ph-photo,.profile-hero .ph-photo-empty{margin:auto}.profile-hero .ph-info .ph-actions{justify-content:center}.profile-hero .ph-qr{justify-self:center}}</style>'''
        body=css+body
        return original(body,status,ctype,headers)
    H.employee_profile=profile

    # Dashboard action center: inject a compact actionable block, not another chart wall.
    old_dash=H.dashboard
    def dashboard(self,u):
        captured=[]; original=self.send
        def cap(body,status=200,ctype='text/html; charset=utf-8',headers=None): captured.append((body,status,ctype,headers))
        self.send=cap
        try: old_dash(self,u)
        finally: self.send=original
        if not captured:return
        body,status,ctype,headers=captured[0]
        if status!=200 or 'text/html' not in ctype:return original(body,status,ctype,headers)
        if isinstance(body,bytes):body=body.decode('utf-8','replace')
        cond,args=visible_sql(u,'e'); c=db()
        def count(sql):
            try:return int(c.execute(sql,args).fetchone()[0])
            except Exception:return 0
        leaves=count("SELECT COUNT(*) FROM leaves l JOIN employees e ON e.emp_code=l.emp_code WHERE l.status IN ('pending','معلق','submitted')"+cond)
        docs=count("SELECT COUNT(*) FROM documents d JOIN employees e ON e.emp_code=d.emp_code WHERE d.status='current' AND d.expiry_date IS NOT NULL AND d.expiry_date<>'' AND d.expiry_date<=date('now','+30 day')"+cond)
        contracts=count("SELECT COUNT(*) FROM contracts ct JOIN employees e ON e.emp_code=ct.emp_code WHERE ct.end_date IS NOT NULL AND ct.end_date<>'' AND ct.end_date<=date('now','+30 day') AND ct.end_date>=date('now')"+cond)
        missing=count("SELECT COUNT(*) FROM employees e LEFT JOIN contracts ct ON ct.emp_code=e.emp_code AND ct.status NOT IN ('terminated','expired') WHERE e.status<>\"مؤرشف\" AND ct.id IS NULL"+cond)
        c.close()
        card=f'''<div class="card action-center no-print" style="margin:16px 0"><div class="top"><div><h2 style="margin:0">📥 يحتاج إجراء</h2><p style="margin:4px 0 0;color:#667085">الأهم الآن، بضغطة واحدة.</p></div><a class="btn gray" href="/hr-inbox">فتح مركز الإجراءات</a></div><div class="grid g4"><a class="action-tile" href="/leaves"><b>🏖 {leaves}</b><span>إجازات معلقة</span></a><a class="action-tile" href="/documents"><b>📄 {docs}</b><span>مستندات قريبة الانتهاء</span></a><a class="action-tile" href="/contracts"><b>📑 {contracts}</b><span>عقود قريبة الانتهاء</span></a><a class="action-tile" href="/hr-inbox"><b>⚪ {missing}</b><span>موظفون بدون عقد</span></a></div></div><style>.action-center .action-tile{{padding:16px;border:1px solid #e4e7ec;border-radius:14px;text-decoration:none;background:#f8fafc}}.action-center .action-tile b{{display:block;font-size:24px}}.action-center .action-tile span{{display:block;color:#667085;margin-top:5px}}</style>'''
        pos=body.find('</div>',body.find('<div class="top"'))
        # Safer insertion: before first major grid/card after top header.
        idx=body.find('<div class="grid',body.find('<div class="top"'))
        if idx<0: idx=body.find('<div class="card')
        body=body[:idx]+card+body[idx:] if idx>=0 else card+body
        return original(body,status,ctype,headers)
    H.dashboard=dashboard

    # Assets POST handlers are intentionally tiny and transactional.
    def assets_post(self,u,f):
        if not can(u,'employees.edit'): return self.forbid(u)
        action=f.get('action','save'); c=db()
        if action=='return':
            try: aid=int(f.get('id') or 0)
            except Exception: aid=0
            r=c.execute('SELECT emp_code FROM employee_assets WHERE id=?',(aid,)).fetchone()
            if not r or not emp_allowed(u,r['emp_code']): c.close(); return self.forbid(u)
            c.execute('UPDATE employee_assets SET status="returned",returned_date=?,updated_at=? WHERE id=?',(f.get('returned_date') or date.today().isoformat(),now(),aid)); c.commit(); c.close(); g['audit'](u['username'],u['role'],'ASSET_RETURN','Employee Assets',str(aid)); return self.redirect('/assets')
        emp=f.get('emp_code','').strip()
        if not emp or not emp_allowed(u,emp): c.close(); return self.forbid(u)
        c.execute('INSERT INTO employee_assets(emp_code,asset_type,asset_no,description,issued_date,status,notes,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(emp,f.get('asset_type','Other'),f.get('asset_no','').strip(),f.get('description','').strip(),f.get('issued_date') or date.today().isoformat(),'issued',f.get('notes',''),u['username'],now(),now())); c.commit(); c.close(); g['audit'](u['username'],u['role'],'ASSET_ISSUE','Employee Assets',emp,f.get('asset_type','Other')); return self.redirect('/assets')
    old_post2=H.do_POST
    def post2(self):
        p=urlparse(self.path).path
        if p=='/qr/generate-all':
            u=self.require()
            if not u:return
            if not is_admin(u): return self.forbid(u)
            f=self.form()
            if f.get('_csrf')!=u.get('csrf'):
                return self.send(page('Security','<div class=\"card\"><div class=\"alert\">Invalid CSRF.</div></div>',u),403)
            qs=parse_qs(urlparse(self.path).query)
            try: offset=max(0,int(qs.get('offset',['0'])[0] or 0)); limit=min(12,max(1,int(qs.get('limit',['8'])[0] or 8)))
            except Exception: offset,limit=0,8
            c=db(); all_codes=[r['emp_code'] for r in c.execute("SELECT e.emp_code FROM employees e WHERE e.status<>'مؤرشف' ORDER BY e.name").fetchall()]; c.close()
            batch=all_codes[offset:offset+limit]; created=0; errors=[]
            for code in batch:
                try:
                    # Use the enterprise QR issuer installed earlier in the process.
                    issue=g.get('issue_qr') or g.get('ensure_token')
                    if issue:
                        issue(code,u,False); created+=1
                    else: errors.append([code,'QR engine unavailable'])
                except Exception as ex:
                    errors.append([code,str(ex)])
            processed=min(offset+len(batch),len(all_codes)); done=processed>=len(all_codes)
            if done:
                try:g['audit'](u['username'],u['role'],'QR_BULK_GENERATE','QR Identity',str(created),f'{created} created; {len(errors)} failed')
                except Exception:pass
            return self.send(json.dumps({'created':created,'total':len(all_codes),'processed':processed,'done':done,'errors':errors},ensure_ascii=False).encode(),200,'application/json',{'Cache-Control':'no-store'})
        if p in ('/assets/save','/assets/action'):
            u=self.require()
            if not u:return
            f=self.form()
            if f.get('_csrf')!=u.get('csrf'): return self.send(page('Security','<div class="card"><div class="alert">Invalid CSRF.</div></div>',u),403)
            return assets_post(self,u,f)
        return old_post2(self)
    H.do_POST=post2

    # Export the installed QR issuer so the batch endpoint can process small chunks.
    if 'issue_qr' not in g: g['issue_qr']=None
    # Add simple navigation links through the latest page function.
    old_page=g['page']
    def page_plus(title,body,user,active='dashboard'):
        out=old_page(title,body,user,active)
        if user and can(user,'employees.view'):
            extra='<a href="/hr-inbox">📥 مركز إجراءات HR</a><a href="/assets">📦 عهد الموظفين</a>'
            out=out.replace('</nav>',extra+'</nav>',1)
        return out
    g['page']=page_plus

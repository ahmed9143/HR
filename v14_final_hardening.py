import os, io, json, csv, re
from urllib.parse import urlparse, quote
from datetime import date, timedelta


def install(g):
    H=g['H']; db=g['db']; page=g['page']; esc=g['esc']; csrf_field=g['csrf_field']; can=g['can']; emp_allowed=g['emp_allowed']; now=g['now']
    old_get=H.do_GET; old_post=H.do_POST

    def admin(u): return bool(u and u.get('role') in ('Admin','SuperAdmin'))
    def hr_or_manager(u): return bool(u and (u.get('role') in ('HR','Manager','Admin','SuperAdmin') or can(u,'employees.edit')))

    # Final GET data-boundary layer: protect direct downloads and ID artifacts.
    protected_prefixes=('/document/','/id-card/','/id-card-pdf/')
    def get(self):
        p=urlparse(self.path).path
        needs_user = p.startswith(protected_prefixes) or p in ('/export/employee-master','/export/qr-bundle','/employee/onboarding','/permissions/matrix') or p.startswith('/employee/onboarding/')
        if not needs_user:
            return old_get(self)
        u=self.require()
        if not u: return None
        if p.startswith(protected_prefixes):
            # Resolve the employee code before allowing the underlying renderer to run.
            code=None
            try:
                if p.startswith('/document/'):
                    did=int(p.rsplit('/',1)[1]); c=db(); r=c.execute('SELECT emp_code FROM documents WHERE id=?',(did,)).fetchone(); c.close(); code=r['emp_code'] if r else None
                else:
                    code=p.rsplit('/',1)[1]
            except Exception: code=None
            if code and not emp_allowed(u,code): return self.forbid(u)
            if not code and p.startswith('/document/'): return self.forbid(u)
            return old_get(self)
        # Employee master / QR bundle are exports containing employee-bound data.
        if p in ('/export/employee-master','/export/qr-bundle'):
            if not can(u,'reports.export') and not admin(u): return self.forbid(u)
            return old_get(self)
        if p=='/employee/onboarding': return onboarding_index(self,u)
        m=re.match(r'^/employee/onboarding/(.+)$',p)
        if m:
            code=m.group(1)
            if not emp_allowed(u,code): return self.forbid(u)
            return onboarding(self,u,code)
        if p=='/permissions/matrix': return permission_matrix(self,u)
        return old_get(self)
    H.do_GET=get

    # Payroll approve/lock already enforce emp_allowed() in their native handlers.

    # ---------------- Documents checklist ----------------
    def documents_checklist(u,code):
        if not emp_allowed(u,code): return ''
        required=['هوية','مؤهل','عقد','تعيين','تأمين']
        c=db(); docs=c.execute("SELECT category,expiry_date,status FROM documents WHERE emp_code=? AND status='current'",(code,)).fetchall(); c.close()
        today=date.today(); by={r['category']:r for r in docs}; parts=[]; complete=0
        for cat in required:
            r=by.get(cat); status='missing'; label='ناقص'; cls='b-bad'
            if r:
                exp=r['expiry_date'] or ''
                if exp:
                    try:
                        d=date.fromisoformat(exp); delta=(d-today).days
                        if delta<0: status='expired'; label='منتهي'; cls='b-bad'
                        elif delta<=30: status='expiring'; label=f'قرب الانتهاء · {delta} يوم'; cls='b-warn'
                        else: status='current'; label='ساري'; cls='b-ok'
                    except Exception: status='current'; label='موجود'; cls='b-ok'
                else: status='current'; label='موجود'; cls='b-ok'
            if status in ('current',): complete+=1
            parts.append(f'<div class="check-row"><span>{"✓" if status=="current" else "!"}</span><b>{esc(cat)}</b><span class="badge {cls}">{esc(label)}</span></div>')
        return f'<div class="card checklist"><div class="top"><div><h3>📄 ملف الأوراق</h3><p>حالة المستندات الأساسية للموظف.</p></div><strong>{complete}/{len(required)} مكتمل</strong></div>{"".join(parts)}<a class="btn gray" href="/documents?emp_code={quote(code)}">إدارة المستندات</a></div>'

    # ---------------- Onboarding ----------------
    def onboarding(self,u,code):
        c=db(); e=c.execute('SELECT * FROM employees WHERE emp_code=?',(code,)).fetchone();
        docs=c.execute("SELECT DISTINCT category FROM documents WHERE emp_code=? AND status='current'",(code,)).fetchall()
        qr=c.execute("SELECT id FROM qr_identities WHERE emp_code=? AND status='active' LIMIT 1",(code,)).fetchone()
        contract=c.execute("SELECT id FROM contracts WHERE emp_code=? AND status NOT IN ('terminated','expired') LIMIT 1",(code,)).fetchone()
        link=c.execute("SELECT username FROM employee_user_links WHERE emp_code=? LIMIT 1",(code,)).fetchone(); assets=c.execute("SELECT id FROM employee_assets WHERE emp_code=? LIMIT 1",(code,)).fetchone() if self_table_exists(c,'employee_assets') else None; c.close()
        if not e:return self.send(page('Onboarding','<div class="card"><div class="alert">الموظف غير موجود.</div></div>',u,'employees'),404)
        checks=[('الملف الأساسي',True,'/employee/edit/'+quote(code)),('الصورة',any(r['category']=='صورة' for r in docs),'/employee/profile/'+quote(code)),('المستندات الأساسية',all(any(r['category']==x for r in docs) for x in ('هوية','مؤهل')), '/documents?emp_code='+quote(code)),('العقد',bool(contract),'/contracts'),('الحساب',bool(link),'/employee/profile/'+quote(code)),('QR',bool(qr),'/employee/profile/'+quote(code)),('العهدة',bool(assets),'/assets')]
        done=sum(1 for _,ok,_ in checks if ok); rows=''.join(f'<div class="on-row"><span class="on-icon">{"✓" if ok else "○"}</span><b>{esc(name)}</b><span class="badge {"b-ok" if ok else "b-warn"}">{"مكتمل" if ok else "يحتاج إجراء"}</span><a class="btn gray" href="{href}">فتح</a></div>' for name,ok,href in checks)
        body=f'<div class="top"><div class="title"><h1>🚀 تجهيز الموظف</h1><p>{esc(e["name"])} · {esc(code)} — {done}/{len(checks)} خطوات مكتملة</p></div><a class="btn gray" href="/employee/profile/{quote(code)}">ملف الموظف</a></div><div class="card"><div class="progress"><div style="width:{round(done*100/len(checks))}%"></div></div>{rows}</div><style>.on-row{{display:grid;grid-template-columns:34px 1fr auto auto;gap:12px;align-items:center;padding:14px 4px;border-bottom:1px solid #eef2f6}}.on-icon{{font-size:22px}}.progress{{height:10px;background:#eef2f6;border-radius:20px;overflow:hidden;margin-bottom:12px}}.progress>div{{height:100%;background:#175cd3}}@media(max-width:650px){{.on-row{{grid-template-columns:30px 1fr auto}}.on-row .btn{{grid-column:2/-1}}}}</style>'
        self.send(page('تجهيز الموظف',body,u,'employees'))
    def self_table_exists(c,name):
        return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone())

    def onboarding_index(self,u):
        if not can(u,'employees.view'): return self.forbid(u)
        cond,args=g['visible_employee_sql'](u,'e'); c=db(); rows=c.execute('SELECT e.emp_code,e.name,e.department,e.status FROM employees e WHERE e.status<>"مؤرشف"'+cond+' ORDER BY e.name LIMIT 500',args).fetchall(); c.close()
        trs=''.join(f'<tr><td>{esc(r["emp_code"])}</td><td>{esc(r["name"])}</td><td>{esc(r["department"] or "—")}</td><td><a class="btn gray" href="/employee/onboarding/{quote(r["emp_code"])}">فتح التجهيز</a></td></tr>' for r in rows)
        self.send(page('Onboarding',f'<div class="top"><div class="title"><h1>🚀 تجهيز الموظفين</h1><p>متابعة جاهزية ملف الموظف خطوة بخطوة.</p></div></div><div class="card table-wrap"><table class="table"><thead><tr><th>الكود</th><th>الموظف</th><th>الإدارة</th><th></th></tr></thead><tbody>{trs or "<tr><td colspan=4>لا يوجد موظفون</td></tr>"}</tbody></table></div>',u,'employees'))

    # ---------------- Permission matrix ----------------
    def permission_matrix(self,u):
        if not admin(u) and not can(u,'roles.manage'): return self.forbid(u)
        rows=[('الموظفون','employees.view','employees.edit'),('الصورة','employees.view','Admin فقط للتعديل'),('QR','employees.view','Admin فقط للتوليد'),('المرتبات','payroll.view','payroll.manage'),('العقود','employees.view','employees.edit'),('التدريب','employees.view','employees.edit'),('العهد','employees.view','employees.edit'),('المستندات','documents.manage','documents.manage'),('الحضور','attendance.view','attendance.edit'),('التقارير','reports.view','reports.export')]
        roles=['Admin','HR','Manager','Employee']; trs=''
        for label,view,edit in rows:
            cells=[]
            for role in roles:
                if role=='Admin': v='✓'; e='✓'
                elif role=='Employee': v='نفسه'; e='—'
                elif role=='Manager': v='Scope'; e='Scope'
                else: v='✓'; e='✓'
                cells.append(f'<td>{v} / {e}</td>')
            trs+=f'<tr><td><b>{esc(label)}</b><br><small>{esc(view)} · {esc(edit)}</small></td>{"".join(cells)}</tr>'
        body=f'<div class="top"><div class="title"><h1>🔐 Permission Matrix</h1><p>مرجع بصري للصلاحيات؛ الـbackend يظل مصدر القرار النهائي.</p></div></div><div class="card table-wrap"><table class="table"><thead><tr><th>الوحدة</th><th>Admin</th><th>HR</th><th>Manager</th><th>Employee</th></tr></thead><tbody>{trs}</tbody></table></div><div class="card" style="margin-top:16px"><div class="alert">Scope = نفس صلاحية الوحدة لكن فقط للموظفين داخل النطاق. Employee = بياناته فقط. QR والتعديل على صورة الموظف محجوزان للـAdmin.</div></div>'
        self.send(page('Permission Matrix',body,u,'roles'))

    # ---------------- Profile 360 hero ----------------
    old_profile=H.employee_profile
    def profile_360(self,u,code):
        captured=[]; orig=self.send
        def cap(body,status=200,ctype='text/html; charset=utf-8',headers=None): captured.append((body,status,ctype,headers))
        self.send=cap
        try: old_profile(self,u,code)
        finally: self.send=orig
        if not captured:return
        body,status,ctype,headers=captured[0]
        if status!=200 or 'text/html' not in ctype:return orig(body,status,ctype,headers)
        s=body.decode('utf-8','replace') if isinstance(body,bytes) else body
        if not emp_allowed(u,code): return self.forbid(u)
        c=db(); e=c.execute('SELECT name,job,department,unit,status,phone FROM employees WHERE emp_code=?',(code,)).fetchone(); qr=c.execute("SELECT status FROM qr_identities WHERE emp_code=? AND status='active' LIMIT 1",(code,)).fetchone(); photo=c.execute("SELECT id FROM documents WHERE emp_code=? AND category='صورة' AND status='current' ORDER BY id DESC LIMIT 1",(code,)).fetchone(); c.close()
        if not e:return orig(body,status,ctype,headers)
        photo_url=f'/employee/photo/{quote(code)}' if photo else ''
        media=f'<img src="{photo_url}" alt="صورة الموظف">' if photo else '<div class="avatar">👤</div>'
        qr_html=f'<img src="/qr/image/{quote(code)}" alt="QR">' if qr else '<div class="qr-empty">لا يوجد QR</div>'
        admin_actions=''
        if admin(u):
            admin_actions=f'<div class="actions"><a class="btn" href="/employee/edit/{quote(code)}">تعديل البيانات</a><a class="btn gray" href="/employee/onboarding/{quote(code)}">تجهيز الموظف</a></div>'
        hero=f'''<section class="profile-hero"><div class="profile-media">{media}</div><div class="profile-main"><span class="badge b-ok">{esc(e['status'] or 'نشط')}</span><h1>{esc(e['name'])}</h1><p>{esc(e['job'] or '—')} · {esc(e['department'] or '—')} · {esc(e['unit'] or '—')}</p><div class="profile-facts"><span>🆔 {esc(code)}</span><span>📞 {esc(e['phone'] or '—')}</span></div>{admin_actions}</div><div class="profile-qr"><div class="qr-label">QR Identity</div>{qr_html}<small>{'Active' if qr else 'غير مُصدر'}</small></div></section>'''
        s=s.replace('<div class="top">',hero+'<div class="top">',1)
        checklist=documents_checklist(u,code)
        s=s.replace('<div class="card"',checklist+'<div class="card"',1) if checklist else s
        css='''<style>.profile-hero{display:grid;grid-template-columns:140px 1fr 170px;gap:22px;align-items:center;background:linear-gradient(135deg,#fff,#f7fbff);border:1px solid #e4e7ec;border-radius:24px;padding:22px;margin-bottom:16px;box-shadow:0 14px 45px rgba(16,24,40,.07)}.profile-media img,.profile-media .avatar{width:140px;height:160px;border-radius:20px;object-fit:cover;background:#eef2f6;display:grid;place-items:center;font-size:54px}.profile-main h1{margin:8px 0 4px;font-size:32px}.profile-main p{color:#667085;margin:0 0 12px}.profile-facts{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px}.profile-facts span{padding:8px 11px;background:#f2f4f7;border-radius:10px}.profile-qr{text-align:center;border:1px dashed #cbd5e1;border-radius:18px;padding:12px;background:#fff}.profile-qr img{width:120px;height:120px;display:block;margin:auto}.qr-empty{height:120px;display:grid;place-items:center;color:#98a2b3;background:#f8fafc;border-radius:12px}.qr-label{font-weight:800;margin-bottom:7px}.checklist{margin-bottom:16px}.check-row{display:grid;grid-template-columns:30px 1fr auto;gap:10px;align-items:center;padding:10px 0;border-bottom:1px solid #eef2f6}.check-row:last-of-type{margin-bottom:12px}@media(max-width:760px){.profile-hero{grid-template-columns:90px 1fr}.profile-media img,.profile-media .avatar{width:90px;height:110px}.profile-qr{grid-column:1/-1}.profile-main h1{font-size:24px}}@media(max-width:480px){.profile-hero{grid-template-columns:1fr;text-align:center}.profile-media img,.profile-media .avatar{margin:auto}.profile-facts,.profile-main .actions{justify-content:center}} </style>'''
        s=s.replace('</body>',css+'</body>',1)
        return orig(s,status,ctype,headers)
    H.employee_profile=profile_360

    # Add navigation entries without replacing the existing navigation system.
    old_page=g['page']
    def page_final(title,body,user,active='dashboard'):
        out=old_page(title,body,user,active)
        if user and can(user,'employees.view'):
            if '/hr-inbox' not in out:
                link='<a href="/hr-inbox">📥 HR Inbox</a>'
                out=out.replace('</nav>',link+'</nav>',1) if '</nav>' in out else out
            if '/employee/onboarding' not in out:
                link='<a href="/employee/onboarding">🚀 تجهيز الموظفين</a>'
                out=out.replace('</nav>',link+'</nav>',1) if '</nav>' in out else out
            if admin(user) and '/permissions/matrix' not in out:
                link='<a href="/permissions/matrix">🔐 Permission Matrix</a>'
                out=out.replace('</nav>',link+'</nav>',1) if '</nav>' in out else out
        return out
    g['page']=page_final


    # Tighten the legacy bulk-user confirmation page: account provisioning is admin-only.
    if hasattr(H,'bulk_users_confirm'):
        old_bulk_users=H.bulk_users_confirm
        def bulk_users_scoped(self,u):
            if not admin(u): return self.forbid(u)
            return old_bulk_users(self,u)
        H.bulk_users_confirm=bulk_users_scoped

    # expose checklist helper for future modules
    g['documents_checklist_v14']=documents_checklist
    g['V14_FINAL_HARDENING']=True


# Production Employee Operations Center
import os, io, csv, json, zipfile, secrets, hashlib, re, mimetypes
from urllib.parse import quote, urlparse
from datetime import datetime

def install_production_ops(g):
    H=g['H']; db=g['db']; now=g['now']; page=g['page']; esc=g['esc']; csrf=g['csrf_field']; can=g['can']; DATA=g['DATA']; EMPFILES=g['EMPFILES']; safe_name=g['safe_name']
    import sys
    vendor=os.path.join(os.path.dirname(__file__),'vendor')
    if os.path.isdir(vendor) and vendor not in sys.path: sys.path.insert(0,vendor)
    try:
        import qrcode as qrmod
    except Exception:
        qrmod=None
    try:
        from openpyxl import Workbook
    except Exception:
        Workbook=None

    def ensure_schema():
        c=db()
        cols={r['name'] for r in c.execute('PRAGMA table_info(users)').fetchall()}
        if 'employee_code' not in cols: c.execute('ALTER TABLE users ADD COLUMN employee_code TEXT')
        c.execute('CREATE INDEX IF NOT EXISTS idx_users_employee_code ON users(employee_code)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_documents_emp_category_status ON documents(emp_code,category,status)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_qr_emp_status ON qr_identities(emp_code,status)')
        c.commit(); c.close()
    old_init=g['init']
    def init_wrapped():
        old_init(); ensure_schema()
    g['init']=init_wrapped

    def password():
        return secrets.token_urlsafe(12).replace('-','A').replace('_','9')[:14]+'!'

    AR=str.maketrans({'ا':'a','أ':'a','إ':'a','آ':'a','ب':'b','ت':'t','ث':'th','ج':'g','ح':'h','خ':'kh','د':'d','ذ':'dh','ر':'r','ز':'z','س':'s','ش':'sh','ص':'s','ض':'d','ط':'t','ظ':'z','ع':'a','غ':'gh','ف':'f','ق':'q','ك':'k','ل':'l','م':'m','ن':'n','ه':'h','و':'w','ي':'y','ى':'y','ة':'h','ؤ':'w','ئ':'y','ء':'a'})
    def username_for(name,emp):
        parts=[]
        for x in str(name or '').split():
            y=re.sub(r'[^a-z0-9]+','',x.translate(AR).lower())
            if y: parts.append(y)
        base='.'.join(parts[:2]) or re.sub(r'[^a-zA-Z0-9._-]','',str(emp)) or 'employee'
        return base[:70]

    def create_user(emp,user):
        if not can(user,'users.manage'): raise PermissionError('لا تملك صلاحية إدارة المستخدمين')
        if not g['emp_allowed'](user,emp): raise PermissionError('الموظف خارج نطاق صلاحيتك')
        c=db(); e=c.execute('SELECT emp_code,name FROM employees WHERE emp_code=?',(emp,)).fetchone()
        if not e: c.close(); raise ValueError('Employee not found')
        existing=c.execute('SELECT id,username FROM users WHERE employee_code=? ORDER BY id DESC LIMIT 1',(emp,)).fetchone()
        if existing:
            c.close(); return existing['username'],'',False
        uname=username_for(e['name'],emp); base=uname; n=1
        while c.execute('SELECT id FROM users WHERE username=?',(uname,)).fetchone():
            n+=1; uname=f'{base}{n}'
        pw=password()
        c.execute("INSERT INTO users(username,password_hash,role,full_name,employee_code,must_change_password,scope_type,scope_value,active) VALUES(?,?,?,?,?,1,'self',?,1)",(uname,g['hashpw'](pw),'Employee',e['name'],emp,emp))
        c.commit(); c.close()
        g['audit'](user['username'],user['role'],'EMPLOYEE_USER_CREATED','User Account',emp,uname)
        return uname,pw,True

    def matrix_png(matrix,scale=8):
        import struct, zlib
        n=len(matrix); w=h=n*scale; raw=bytearray()
        for y in range(h):
            raw.append(0); row=matrix[y//scale]
            for x in range(w):
                v=0 if row[x//scale] else 255; raw.extend((v,v,v))
        def chunk(kind,data):
            return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
        return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',w,h,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(bytes(raw),9))+chunk(b'IEND',b'')

    def issue_qr(emp,user,regenerate=False):
        if not qrmod: raise RuntimeError('QR engine unavailable. The bundled QR engine is missing.')
        c=db(); e=c.execute('SELECT emp_code FROM employees WHERE emp_code=?',(emp,)).fetchone(); old=c.execute('SELECT * FROM qr_identities WHERE emp_code=?',(emp,)).fetchone(); c.close()
        if not e: raise ValueError('Employee not found')
        if old and old['status']=='active' and old['image_path'] and not regenerate and os.path.exists(os.path.join(DATA,old['image_path'])): return False
        token=secrets.token_urlsafe(32)
        q=qrmod.QRCode(version=None,error_correction=qrmod.constants.ERROR_CORRECT_H,box_size=8,border=4)
        base=(g['setting']('server_url') or '').strip().rstrip('/') or f"http://{g['local_ip']()}:{g['PORT']}"
        q.add_data(base+'/qr/verify/'+token); q.make(fit=True)
        matrix=q.get_matrix()
        raw=matrix_png(matrix,8)
        qdir=os.path.join(DATA,'qr'); os.makedirs(qdir,exist_ok=True)
        rel=os.path.join('qr',hashlib.sha256(emp.encode('utf-8')).hexdigest()[:24]+'.png').replace('\\','/')
        with open(os.path.join(DATA,rel),'wb') as fh: fh.write(raw)
        th=hashlib.sha256(token.encode()).hexdigest()
        c=db()
        if old:
            c.execute('UPDATE qr_identities SET token_hash=?,issued_at=?,revoked_at=NULL,status="active",created_by=?,regenerated_from=?,image_path=? WHERE emp_code=?',(th,now(),user['username'],old['token_hash'],rel,emp))
        else:
            c.execute('INSERT INTO qr_identities(emp_code,token_hash,issued_at,status,created_by,regenerated_from,image_path) VALUES(?,?,?,?,?,?,?)',(emp,th,now(),'active',user['username'],None,rel))
        c.commit(); c.close(); g['audit'](user['username'],user['role'],'QR_CREATED' if not old else 'QR_REGENERATED','QR Identity',emp,'active')
        return True

    def export_package(user, include_credentials=True):
        if not can(user,'reports.export'): raise PermissionError('لا تملك صلاحية التصدير')
        c=db(); emps=c.execute("SELECT * FROM employees WHERE status<>'مؤرشف' ORDER BY name").fetchall(); c.close()
        out=io.BytesIO(); credentials=[]
        with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
            if Workbook:
                wb=Workbook(); ws=wb.active; ws.title='Employees'
                headers=['Employee ID','Name','National ID','Phone','Email','Job','Department','Unit','Location','Gender','Hire Date','Status','Basic Salary','Allowances','Total Salary','Birth Date','Address','Qualification','IBAN','Bank','Bank Branch','Contract Date','Contract Amount','Username','User Role','User Status','QR Status','QR Issued']
                ws.append(headers)
            else: wb=None; ws=None
            for e in emps:
                emp=e['emp_code']; uname=''; role=''; active=''; qrstatus=''; issued=''
                c=db(); ur=c.execute('SELECT username,role,active FROM users WHERE employee_code=? ORDER BY id DESC LIMIT 1',(emp,)).fetchone(); qr=c.execute('SELECT status,issued_at,image_path FROM qr_identities WHERE emp_code=? AND status="active" ORDER BY id DESC LIMIT 1',(emp,)).fetchone(); docs=c.execute('SELECT id,file_name,category,storage_path,data FROM documents WHERE emp_code=? AND status="current" ORDER BY id',(emp,)).fetchall(); c.close()
                if ur: uname,role,active=ur['username'],ur['role'],ur['active']
                if qr: qrstatus,issued=qr['status'],qr['issued_at']
                if ws: ws.append([e[h] if h in e.keys() else '' for h in ['emp_code','name','national_id','phone','email','job','department','unit','location','gender','hire_date','status','basic_salary','allowances','total_salary','birth_date','address','qualification','iban','bank_name','bank_branch','contract_date','contract_amount']] + [uname,role,active,qrstatus,issued])
                base='Employees/'+safe_name(emp)+'/'; z.writestr(base+'employee.json',json.dumps(dict(e),ensure_ascii=False,default=str,indent=2))
                for d in docs:
                    data=None
                    if d['storage_path']:
                        try: data=g['secure_file_bytes'](d['storage_path'])
                        except Exception: data=None
                    if data is None and d['data'] is not None: data=d['data']
                    if data is not None:
                        fn=safe_name(d['file_name'] or ('document_'+str(d['id']))); z.writestr(base+safe_name(d['category'] or 'General')+'/'+fn,data)
                if qr and qr['image_path'] and os.path.exists(os.path.join(DATA,qr['image_path'])):
                    z.write(os.path.join(DATA,qr['image_path']),'QR/'+safe_name(emp)+'.png')
                if include_credentials:
                    # Reuse existing password is impossible by design; bulk provisioning generates it below.
                    pass
            if ws:
                x=io.BytesIO(); wb.save(x); z.writestr('employees_master.xlsx',x.getvalue())
            z.writestr('README.txt','HR Enterprise Employee Master Export\nContains employee data, documents, photos and QR images.\nTreat this archive as confidential.\n')
            if credentials:
                s=io.StringIO(); w=csv.writer(s); w.writerow(['Employee ID','Name','Username','Temporary Password','Role','QR Status']); w.writerows(credentials); z.writestr('employee_credentials.csv',s.getvalue().encode('utf-8-sig'))
        return out.getvalue()

    def bulk_provision(user):
        if not can(user,'users.manage'): raise PermissionError('لا تملك صلاحية إدارة المستخدمين')
        c=db(); rows=c.execute("SELECT emp_code,name FROM employees WHERE status<>'مؤرشف' ORDER BY name").fetchall(); c.close()
        results=[]; errors=[]
        for r in rows:
            emp=r['emp_code']
            if not g['emp_allowed'](user,emp): continue
            try:
                uname,pw,created=create_user(emp,user); issue_qr(emp,user,False)
                os.makedirs(os.path.join(EMPFILES,safe_name(emp)),exist_ok=True)
                results.append((emp,r['name'],uname,pw,'Employee','active' if created else 'existing-password-not-exported'))
            except Exception as ex:
                errors.append((emp,str(ex)))
        # Export generated credentials plus full employee package in one archive.
        c=db(); emps=c.execute("SELECT * FROM employees WHERE status<>'مؤرشف' ORDER BY name").fetchall(); c.close()
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
            if Workbook:
                wb=Workbook(); ws=wb.active; ws.title='Employees'
                ws.append(['Employee ID','Name','Username','Temporary Password','Role','QR Status'])
                for row in results: ws.append(row)
                x=io.BytesIO(); wb.save(x); z.writestr('employee_accounts.xlsx',x.getvalue())
            s=io.StringIO(); w=csv.writer(s); w.writerow(['Employee ID','Name','Username','Temporary Password','Role','QR Status']); w.writerows(results); z.writestr('employee_accounts.csv',s.getvalue().encode('utf-8-sig'))
            for r in results:
                emp=r[0]; p=os.path.join(DATA,'qr',hashlib.sha256(emp.encode('utf-8')).hexdigest()[:24]+'.png')
                if os.path.exists(p): z.write(p,'QR/'+safe_name(emp)+'.png')
            for e in emps:
                emp=e['emp_code']; base='Employees/'+safe_name(emp)+'/'; z.writestr(base+'employee.json',json.dumps(dict(e),ensure_ascii=False,default=str,indent=2)); os.makedirs(os.path.join(EMPFILES,safe_name(emp)),exist_ok=True)
                c=db(); docs=c.execute('SELECT id,file_name,category,storage_path,data FROM documents WHERE emp_code=? AND status="current" ORDER BY id',(emp,)).fetchall(); c.close()
                for d in docs:
                    data=None
                    if d['storage_path']:
                        try: data=g['secure_file_bytes'](d['storage_path'])
                        except Exception: pass
                    if data is None and d['data'] is not None: data=d['data']
                    if data is not None: z.writestr(base+safe_name(d['category'] or 'General')+'/'+safe_name(d['file_name'] or ('document_'+str(d['id']))),data)
            z.writestr('README.txt','CONFIDENTIAL\nBulk account provisioning export. Passwords are temporary and must be changed at first login.\nErrors: '+json.dumps(errors,ensure_ascii=False))
        g['audit'](user['username'],user['role'],'BULK_EMPLOYEE_PROVISION','Employee Operations','bulk',f'created={len(results)};errors={len(errors)}')
        return out.getvalue(),len(results),errors

    def operations(self,u):
        if not can(u,'employees.view'): return H.forbid(self,u)
        c=db(); total=c.execute("SELECT COUNT(*) n FROM employees WHERE status<>'مؤرشف'").fetchone()['n']; noqr=c.execute("SELECT COUNT(*) n FROM employees e WHERE e.status<>'مؤرشف' AND NOT EXISTS(SELECT 1 FROM qr_identities q WHERE q.emp_code=e.emp_code AND q.status='active')").fetchone()['n']; nouser=c.execute("SELECT COUNT(*) n FROM employees e WHERE e.status<>'مؤرشف' AND NOT EXISTS(SELECT 1 FROM users u WHERE u.employee_code=e.emp_code AND u.active=1)").fetchone()['n']; c.close()
        body=f'''<div class="top"><div class="title"><h1>⚡ Employee Operations Center</h1><p>إنشاء الحسابات + QR + مجلدات الموظفين + Export في عملية واحدة.</p></div></div>
<div class="grid g4"><div class="card metric"><div class="label">الموظفون</div><div class="value">{total}</div></div><div class="card metric"><div class="label">بدون QR</div><div class="value">{noqr}</div></div><div class="card metric"><div class="label">بدون User</div><div class="value">{nouser}</div></div><div class="card metric"><div class="label">مجلدات</div><div class="value">جاهزة</div></div></div>
<div class="card" style="margin-top:16px"><h2>🚀 تنفيذ شامل</h2><p>ينشئ لكل موظف User + Password مؤقت + QR + Folder، ثم ينزل ملف ZIP يحتوي Excel/CSV والحسابات وQR وملفات الموظفين.</p><form method="post" action="/employee/operations/provision">{csrf(u)}<button class="btn" style="font-size:18px;padding:14px 20px">⚡ إنشاء كل شيء وتصدير الملف</button></form><p class="alert">تنبيه: ملف التصدير يحتوي كلمات مرور مؤقتة. احفظه في مكان آمن واحذفه بعد تسليم البيانات.</p></div>
<div class="grid g3" style="margin-top:16px"><div class="card"><h3>🔐 Bulk Users</h3><p>إنشاء/تجديد حسابات الموظفين دفعة واحدة.</p><form method="post" action="/employee/operations/users">{csrf(u)}<button class="btn gray">إنشاء Users فقط</button></form></div><div class="card"><h3>🔳 Bulk QR</h3><p>إنشاء QR لكل موظف بدون QR.</p><form method="post" action="/employee/operations/qr">{csrf(u)}<button class="btn gray">إنشاء QR فقط</button></form></div><div class="card"><h3>📦 Full Export</h3><p>بيانات + مستندات + صور + QR + Excel.</p><a class="btn gray" href="/employee/operations/export">Export Full Package</a></div><div class="card"><h3>📁 Employee Folders</h3><p>إنشاء مجلد مستقل لكل موظف لرفع وحفظ المستندات.</p><a class="btn gray" href="/employee/operations/folders">إنشاء كل المجلدات</a></div></div>'''
        H.send(self,page('Employee Operations',body,u,'employees'))

    old_get=H.do_GET; old_post=H.do_POST
    def get(self):
        p=urlparse(self.path).path
        if p=='/employee/operations':
            u=self.require(); return operations(self,u) if u else None
        if p=='/employee/operations/folders':
            u=self.require()
            if not u: return None
            if not can(u,'documents.bulk_import'): return self.forbid(u)
            c=db(); rows=c.execute("SELECT emp_code,name FROM employees WHERE status<>'مؤرشف' ORDER BY name").fetchall(); c.close(); made=0
            for r in rows:
                if g['emp_allowed'](u,r['emp_code']): os.makedirs(os.path.join(EMPFILES,safe_name(r['emp_code'])),exist_ok=True); made+=1
            return self.send(page('Employee Folders',f'<div class="card"><h2>✅ تم تجهيز {made} مجلد موظف</h2><p>المجلد الرئيسي: employee_files/{esc(made)}</p><a class="btn" href="/import">رفع مستندات من المجلدات</a></div>',u,'employees'))
        if p=='/employee/operations/export':
            u=self.require()
            if not u: return None
            try: data=export_package(u,False); return self.send(data,200,'application/zip',{'Content-Disposition':'attachment; filename="HR_Employee_Full_Export.zip"'})
            except Exception as ex: return self.send(page('Export Error',f'<div class="card"><div class="alert">{esc(ex)}</div></div>',u),400)
        return old_get(self)
    def post(self):
        p=urlparse(self.path).path
        if p in ('/qr/generate','/qr/regenerate','/qr/generate-all','/qr/bulk'):
            u=self.require()
            if not u:return None
            if u.get('must_change_password') and p != '/employee/operations/folders': return self.redirect('/password')
            f=H.form(self)
            if f.get('_csrf')!=u.get('csrf'): return self.send(page('Security','<div class="card"><div class="alert">Invalid CSRF.</div></div>',u),403)
            if p in ('/qr/generate','/qr/regenerate'):
                if not can(u,'employees.edit'): return self.forbid(u)
                emp=f.get('emp_code','').strip()
                if not emp or not g['emp_allowed'](u,emp): return self.forbid(u)
                try:
                    issue_qr(emp,u,p=='/qr/regenerate')
                    return self.redirect('/employee/profile/'+quote(emp))
                except Exception as ex:
                    return self.send(page('QR Error',f'<div class="card"><div class="alert">فشل إنشاء QR للموظف {esc(emp)}: {esc(ex)}</div></div>',u,'employees'),500)
            if p=='/qr/generate-all':
                if not can(u,'employees.edit'): return self.forbid(u)
                c=db(); rows=c.execute("SELECT e.emp_code FROM employees e WHERE e.status<>'مؤرشف' AND NOT EXISTS(SELECT 1 FROM qr_identities q WHERE q.emp_code=e.emp_code AND q.status='active') ORDER BY e.name").fetchall(); c.close(); rows=[r for r in rows if g['emp_allowed'](u,r['emp_code'])]; ok=0; errors=[]
                for r in rows:
                    try: issue_qr(r['emp_code'],u,False); ok+=1
                    except Exception as ex: errors.append([r['emp_code'],str(ex)])
                return self.send(json.dumps({'created':ok,'total':len(rows),'errors':errors},ensure_ascii=False).encode(),200,'application/json; charset=utf-8')
            if p=='/qr/bulk':
                if not can(u,'employees.edit'): return self.forbid(u)
                action=f.get('action','generate'); ids=[x.strip() for x in f.get('emp_codes','').split(',') if x.strip()][:500]; ok=0; errors=[]
                for emp in ids:
                    if not g['emp_allowed'](u,emp): continue
                    try:
                        if action=='revoke':
                            c=db(); c.execute('UPDATE qr_identities SET status="revoked",revoked_at=? WHERE emp_code=? AND status="active"',(now(),emp)); c.commit(); c.close()
                        else: issue_qr(emp,u,action=='regenerate')
                        ok+=1
                    except Exception as ex: errors.append([emp,str(ex)])
                return self.send(json.dumps({'done':ok,'requested':len(ids),'errors':errors},ensure_ascii=False).encode(),200,'application/json; charset=utf-8')
        if p in ('/employee/operations/provision','/employee/operations/users','/employee/operations/qr'):
            u=self.require()
            if not u:return None
            if u.get('must_change_password'):
                return self.redirect('/password')
            f=H.form(self)
            if f.get('_csrf')!=u.get('csrf'): return self.send(page('Security','<div class="card"><div class="alert">Invalid CSRF.</div></div>',u),403)
            if p=='/employee/operations/provision':
                try:
                    data,n,errors=bulk_provision(u); return self.send(data,200,'application/zip',{'Content-Disposition':'attachment; filename="HR_Bulk_Employee_Provisioning.zip"'})
                except Exception as ex: return self.send(page('Provisioning Error',f'<div class="card"><div class="alert">{esc(ex)}</div></div>',u),400)
            if p=='/employee/operations/users':
                if not can(u,'users.manage'): return self.forbid(u)
                c=db(); rows=c.execute("SELECT emp_code FROM employees WHERE status<>'مؤرشف' ORDER BY name").fetchall(); c.close(); rows=[r for r in rows if g['emp_allowed'](u,r['emp_code'])]; result=[]
                for r in rows:
                    try:
                        uname,pw,created=create_user(r['emp_code'],u); result.append((r['emp_code'],uname,pw,'CREATED' if created else 'EXISTING'))
                    except Exception as ex: result.append((r['emp_code'],'','FAILED: '+str(ex),'FAILED'))
                out=io.StringIO(); w=csv.writer(out); w.writerow(['Employee ID','Username','Temporary Password','Status']); w.writerows(result); return self.send(out.getvalue().encode('utf-8-sig'),200,'text/csv; charset=utf-8',{'Content-Disposition':'attachment; filename="Employee_Accounts.csv"'})
            if p=='/employee/operations/qr':
                if not can(u,'employees.edit'): return self.forbid(u)
                c=db(); rows=c.execute("SELECT e.emp_code FROM employees e WHERE e.status<>'مؤرشف' AND NOT EXISTS(SELECT 1 FROM qr_identities q WHERE q.emp_code=e.emp_code AND q.status='active')").fetchall(); c.close(); rows=[r for r in rows if g['emp_allowed'](u,r['emp_code'])]; ok=0; errors=[]
                for r in rows:
                    try: issue_qr(r['emp_code'],u,False); ok+=1
                    except Exception as ex: errors.append((r['emp_code'],str(ex)))
                out=io.StringIO(); w=csv.writer(out); w.writerow(['Employee ID','Status','Error']); [w.writerow([r['emp_code'],'created','']) for r in rows if r['emp_code'] not in dict(errors)]; [w.writerow([a,'failed',b]) for a,b in errors]; return self.send(out.getvalue().encode('utf-8-sig'),200,'text/csv; charset=utf-8',{'Content-Disposition':'attachment; filename="QR_Bulk_Result.csv"'})
        return old_post(self)
    H.do_GET=get; H.do_POST=post

    # Repair the existing photo route: support both filesystem-backed and legacy BLOB photos.
    old_get_photo=H.do_GET
    def get_with_photo(self):
        p=urlparse(self.path).path
        if p.startswith('/employee/photo/'):
            u=self.require()
            if not u:return None
            code=p.split('/employee/photo/',1)[1]
            if not can(u,'employees.view') or not g['emp_allowed'](u,code): return self.forbid(u)
            c=db(); r=c.execute("SELECT id,storage_path,file_name,data FROM documents WHERE emp_code=? AND category='صورة' AND status='current' ORDER BY id DESC LIMIT 1",(code,)).fetchone(); c.close()
            if not r:return self.send(b'',404,'image/png')
            data=None
            if r['storage_path']:
                try:data=g['secure_file_bytes'](r['storage_path'])
                except Exception: data=None
            if data is None and r['data'] is not None:data=r['data']
            if not data:return self.send(b'',404,'image/png')
            return self.send(data,200,mimetypes.guess_type(r['file_name'])[0] or 'image/jpeg',{'Cache-Control':'private,max-age=86400'})
        return old_get_photo(self)
    H.do_GET=get_with_photo

    # Add real bulk controls directly to the Employees page.
    old_employees=H.employees
    def employees_ops(self,u):
        captured=[]; orig=self.send
        def cap(body,status=200,ctype='text/html; charset=utf-8',headers=None): captured.append((body,status,ctype,headers))
        self.send=cap
        try: old_employees(self,u)
        finally: self.send=orig
        if not captured: return
        body,status,ctype,headers=captured[0]
        if status!=200 or 'text/html' not in ctype: return orig(body,status,ctype,headers)
        s=body.decode('utf-8','replace') if isinstance(body,bytes) else body
        marker='<a class="btn" href="/employee/new">+ إضافة موظف</a>'
        token=esc(u.get('csrf',''))
        tools='<a class="btn" href="/employee/operations">⚡ عمليات الموظفين</a><form method="post" action="/employee/operations/users" style="display:inline" onsubmit="return confirm(\'سيتم إنشاء حسابات الموظفين الذين لا يملكون حسابًا وتصدير كلمات المرور الجديدة فقط. هل تريد المتابعة؟\')"><input type="hidden" name="_csrf" value="'+token+'"><button class="btn gray">🔐 Bulk Users</button></form><form method="post" action="/employee/operations/qr" style="display:inline" onsubmit="return confirm(\'سيتم إنشاء QR لكل موظف بدون QR. هل تريد المتابعة؟\')"><input type="hidden" name="_csrf" value="'+token+'"><button class="btn gray">🔳 Bulk QR</button></form><a class="btn gray" href="/employee/operations/export">📦 Full Export</a>'
        if marker in s: s=s.replace(marker,marker+tools,1)
        return orig(s,status,ctype,headers)
    H.employees=employees_ops

    old_page=g['page']
    def page_ops(title,body,user,active='dashboard'):
        out=old_page(title,body,user,active)
        if user and can(user,'employees.view'):
            marker='<a href="/employee/operations"'
            if marker not in out:
                link='<a href="/employee/operations">⚡ مركز عمليات الموظفين</a>'
                out=out.replace('</nav>',link+'</nav>',1) if '</nav>' in out else out.replace('</aside>',link+'</aside>',1)
        return out
    g['page']=page_ops

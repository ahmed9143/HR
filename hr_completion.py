# HR Enterprise completion layer
import os, io, json, secrets, base64, urllib.parse, threading
from datetime import date, timedelta

def install_completion(g):
    _tls=threading.local()
    H=g["H"]; db=g["db"]; now=g["now"]; esc=g["esc"]; page=g["page"]; csrf_field=g["csrf_field"]
    can=g["can"]; audit=g["audit"]; emp_allowed=g["emp_allowed"]; quote=g.get("quote",urllib.parse.quote)

    c=db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS permissions(id INTEGER PRIMARY KEY,code TEXT UNIQUE,name_ar TEXT);
    CREATE TABLE IF NOT EXISTS role_permissions(role TEXT,permission TEXT,PRIMARY KEY(role,permission));
    CREATE TABLE IF NOT EXISTS qr_identities(
      id INTEGER PRIMARY KEY AUTOINCREMENT, emp_code TEXT UNIQUE NOT NULL, token TEXT UNIQUE NOT NULL,
      status TEXT DEFAULT 'active', created_at TEXT NOT NULL, created_by TEXT,
      revoked_at TEXT, revoked_by TEXT, last_verified_at TEXT, last_verified_ip TEXT);
    CREATE INDEX IF NOT EXISTS idx_qr_token ON qr_identities(token);
    CREATE TABLE IF NOT EXISTS contracts(
      id INTEGER PRIMARY KEY AUTOINCREMENT, emp_code TEXT NOT NULL, contract_no TEXT,
      contract_type TEXT DEFAULT 'دوام كامل', start_date TEXT, end_date TEXT, amount REAL DEFAULT 0,
      status TEXT DEFAULT 'active', notes TEXT, document_id INTEGER, created_by TEXT, created_at TEXT, updated_at TEXT);
    CREATE INDEX IF NOT EXISTS idx_contracts_emp_dates ON contracts(emp_code,start_date,end_date);
    CREATE TABLE IF NOT EXISTS training_records(
      id INTEGER PRIMARY KEY AUTOINCREMENT, emp_code TEXT NOT NULL, course TEXT NOT NULL, provider TEXT,
      start_date TEXT, end_date TEXT, expiry_date TEXT, status TEXT DEFAULT 'completed', score REAL DEFAULT 0,
      certificate_no TEXT, notes TEXT, created_by TEXT, created_at TEXT, updated_at TEXT);
    CREATE TABLE IF NOT EXISTS evaluation_cycles(
      id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, start_date TEXT, end_date TEXT,
      status TEXT DEFAULT 'draft', created_by TEXT, created_at TEXT, approved_by TEXT, approved_at TEXT);
    CREATE TABLE IF NOT EXISTS evaluation_records(
      id INTEGER PRIMARY KEY AUTOINCREMENT, cycle_id INTEGER NOT NULL, emp_code TEXT NOT NULL, evaluator TEXT,
      score REAL DEFAULT 0, criteria_json TEXT DEFAULT '{}', comments TEXT, status TEXT DEFAULT 'draft',
      created_by TEXT, created_at TEXT, approved_by TEXT, approved_at TEXT, UNIQUE(cycle_id,emp_code));
    """)
    perms=[("contracts.manage","إدارة العقود"),("training.manage","إدارة التدريب"),
           ("evaluations.manage","إدارة التقييمات"),("qr.manage","إدارة QR وبطاقات الهوية"),
           ("qr.verify","التحقق من QR"),("system.audit","تدقيق النظام")]
    for x,n in perms:c.execute("INSERT OR IGNORE INTO permissions(code,name_ar) VALUES(?,?)",(x,n))
    for role in ("SuperAdmin","Admin","HR"):
        for x,n in perms:
            if role=="HR" and x=="system.audit": continue
            c.execute("INSERT OR IGNORE INTO role_permissions(role,permission) VALUES(?,?)",(role,x))
    for x in ("training.manage","evaluations.manage","qr.verify"):c.execute("INSERT OR IGNORE INTO role_permissions(role,permission) VALUES('Manager',?)",(x,))
    # Migrate legacy training rows into the completion table once, preserving real data.
    try:
        c=db()
        legacy=c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='training'").fetchone()
        if legacy:
            c.execute("INSERT INTO training_records(emp_code,course,provider,start_date,end_date,expiry_date,status,score,certificate_no,notes,created_by,created_at,updated_at) SELECT t.emp_code,t.course,t.trainer,t.training_date,NULL,t.expiry_date,t.status,t.score,t.certificate,t.certificate,t.created_by,t.created_at,t.created_at FROM training t WHERE NOT EXISTS (SELECT 1 FROM training_records tr WHERE tr.emp_code=t.emp_code AND tr.course=t.course AND COALESCE(tr.expiry_date,'')=COALESCE(t.expiry_date,''))")
            c.commit()
        c.close()
    except Exception as e:
        try: c.close()
        except Exception: pass
    c=db();c.close()

    def emp(code):
        c=db();r=c.execute("SELECT * FROM employees WHERE emp_code=?",(code,)).fetchone();c.close();return r
    def qr_png(token):
        import qrcode
        q=qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,box_size=10,border=4)
        q.add_data("/qr/verify/"+token);q.make(fit=True);b=io.BytesIO();q.make_image().save(b,"PNG");return b.getvalue()
    def ensure_qr(u,code,regen=False):
        if not emp_allowed(u,code):return None
        c=db();r=c.execute("SELECT * FROM qr_identities WHERE emp_code=?",(code,)).fetchone()
        if r and not regen:c.close();return r
        token=secrets.token_urlsafe(32)
        if r:
            c.execute("UPDATE qr_identities SET status='revoked',revoked_at=?,revoked_by=? WHERE id=?",(now(),u["username"],r["id"]))
            c.execute("UPDATE qr_identities SET token=?,status='active',created_at=?,created_by=?,revoked_at=NULL,revoked_by=NULL WHERE id=?",(token,now(),u["username"],r["id"]));action="QR_REGENERATED"
        else:
            c.execute("INSERT INTO qr_identities(emp_code,token,status,created_at,created_by) VALUES(?,?,?,?,?)",(code,token,"active",now(),u["username"]));action="QR_CREATED"
        c.commit();r=c.execute("SELECT * FROM qr_identities WHERE emp_code=?",(code,)).fetchone();c.close()
        audit(u["username"],u["role"],action,"QR Identity",code,"opaque token");return r

    def qr_profile(u,code):
        if not emp_allowed(u,code):return H.forbid(_tls.request)
        e=emp(code);r=ensure_qr(u,code)
        qrimg=f'<img src="/qr/image/{quote(code,safe="")}" style="width:320px">' if r and r["status"]=="active" else '<div class="alert">QR غير فعال — اضغط «إعادة إصدار» لإنشاء رمز جديد.</div>'
        body=f"""<div class="top"><div class="title"><h1>🪪 QR Identity</h1><p>{esc(e["name"])} · {esc(code)}</p></div>
        <div class="actions"><a class="btn" href="/id-card/{quote(code,safe="")}">بطاقة الهوية</a><a class="btn gray" href="/qr/scanner">Scanner</a></div></div>
        <div class="card" style="text-align:center">{qrimg}<p><code>{("/qr/verify/"+esc(r["token"])) if r["status"]=="active" else "revoked"}</code></p>
        <form method="post" action="/qr/regenerate" style="display:inline">{csrf_field(u)}<input type="hidden" name="emp_code" value="{esc(code)}"><button class="btn warn">إعادة إصدار</button></form>
        <form method="post" action="/qr/revoke" style="display:inline">{csrf_field(u)}<input type="hidden" name="emp_code" value="{esc(code)}"><button class="btn bad">إلغاء</button></form>
        <p>الـQR لا يحتوي رقم قومي أو راتب أو هاتف أو IBAN.</p></div>"""
        return H.send(_tls.request,page("QR Identity",body,u,"employees"))

    def qr_verify(token):
        c=db();r=c.execute("SELECT q.*,e.name,e.department,e.job,e.status,e.location FROM qr_identities q JOIN employees e ON e.emp_code=q.emp_code WHERE q.token=?",(token,)).fetchone()
        if not r:c.close();return H.send(_tls.request,page("QR","<div class='card'><h2>QR غير صالح</h2></div>",{"role":"","username":"","full_name":"QR Verification"}),404)
        if r["status"]!="active":c.close();return H.send(_tls.request,page("QR","<div class='card'><h2>QR غير فعال</h2></div>",{"role":"","username":"","full_name":"QR Verification"}),410)
        c.execute("UPDATE qr_identities SET last_verified_at=?,last_verified_ip=? WHERE id=?",(now(),getattr(H,"_verify_ip",""),r["id"]));c.commit();c.close()
        audit("QR-SCAN","system","QR_VERIFIED","QR Identity",r["emp_code"],"public verify")
        body=f"""<div class="card" style="max-width:700px;margin:40px auto"><h1>✅ هوية مؤكدة</h1>
        <div class="grid g2"><div><small>الاسم</small><h2>{esc(r["name"])}</h2></div><div><small>Employee ID</small><h2>{esc(r["emp_code"])}</h2></div>
        <div><small>القسم</small><b>{esc(r["department"] or "—")}</b></div><div><small>الوظيفة</small><b>{esc(r["job"] or "—")}</b></div>
        <div><small>الحالة</small><b>{esc(r["status"])}</b></div><div><small>الموقع</small><b>{esc(r["location"] or "—")}</b></div></div></div>"""
        return H.send(_tls.request,page("QR Verification",body,{"role":"","username":"","full_name":"QR Verification"}),200)

    def qr_scanner(u):
        body="""<div class="top"><div class="title"><h1>📷 QR Scanner</h1><p>USB Scanner أو إدخال يدوي، مع كاميرا المتصفح عند دعم BarcodeDetector.</p></div></div>
        <div class="card"><input id="s" autofocus style="width:100%;padding:14px" placeholder="Scan QR ثم Enter">
        <button class="btn" onclick="go()" style="margin-top:10px">تحقق</button><button class="btn gray" onclick="cam()" style="margin-top:10px">الكاميرا</button>
        <video id="v" playsinline style="display:none;width:100%;margin-top:15px"></video><div id="m" class="alert">جاهز.</div></div>
        <script>const s=document.getElementById('s'),v=document.getElementById('v'),m=document.getElementById('m');function go(){let x=s.value.trim(),i=x.indexOf('/qr/verify/');if(i>=0)x=x.slice(i+11);if(x)location='/qr/verify/'+encodeURIComponent(x.split(/[?#]/)[0])}s.onkeydown=e=>{if(e.key==='Enter')go()};async function cam(){if(!('BarcodeDetector'in window)){m.textContent='استخدم USB Scanner؛ الكاميرا غير مدعومة.';return}try{let d=new BarcodeDetector({formats:['qr_code']}),st=await navigator.mediaDevices.getUserMedia({video:{facingMode:'environment'}});v.srcObject=st;v.style.display='block';await v.play();async function f(){let a=await d.detect(v);if(a.length){s.value=a[0].rawValue;go()}else requestAnimationFrame(f)}f()}catch(e){m.textContent=e.message}}</script>"""
        return H.send(_tls.request,page("QR Scanner",body,u,"employees"))

    CARD_CSS="""<style>@media print{@page{size:A4;margin:8mm}.idcard{break-inside:avoid}}body{background:#eee}.cards{display:grid;grid-template-columns:repeat(2,85.6mm);gap:10mm;justify-content:center}.idcard{width:85.6mm;height:54mm;background:#fff;border:1px solid #d0d5dd;border-radius:4mm;overflow:hidden;position:relative;font-family:Arial;direction:ltr}.stripe{height:5mm;background:#175cd3}.ctop{display:flex;justify-content:space-between;padding:4mm 5mm 0;color:#175cd3}.ctop small{display:block;color:#667085;font-size:7px}.photo{width:17mm;height:21mm;object-fit:cover;border-radius:2mm}.cbody{padding:0 5mm}.cbody h2{font-size:15px;margin:1mm 0}.eid{font-weight:800;color:#175cd3}.cbody p{font-size:8px}.cqr{position:absolute;right:5mm;bottom:3mm;text-align:center}.cqr img{width:22mm;height:22mm}.cqr small{display:block;font-size:5px}</style>"""
    def card_html(e,r):
        return f"""<div class="idcard"><div class="stripe"></div><div class="ctop"><b>HR ENTERPRISE</b><small>EMPLOYEE ID CARD</small></div>
        <div class="cbody"><h2>{esc(e["name"])}</h2><div class="eid">{esc(e["emp_code"])}</div><p><b>{esc(e["job"] or "—")}</b><br>{esc(e["department"] or "—")} · {esc(e["unit"] or "—")}</p></div>
        <div class="cqr"><img src="data:image/png;base64,{base64.b64encode(qr_png(r["token"])).decode()}"><small>Scan to verify</small></div></div>"""
    def id_card(u,code):
        if not emp_allowed(u,code):return H.forbid(_tls.request)
        e=emp(code);r=ensure_qr(u,code)
        return H.send(_tls.request,CARD_CSS+'<div style="text-align:center"><button onclick="window.print()">🖨 طباعة</button></div><div class="cards">'+card_html(e,r)+'</div>',200,"text/html")
    def id_cards(u):
        codes=[x for x in urllib.parse.parse_qs(urllib.parse.urlparse(_tls.request.path).query).get("codes",[""])[0].split(",") if x]
        if not codes:
            c=db();codes=[r["emp_code"] for r in c.execute("SELECT emp_code FROM employees WHERE status!='مؤرشف' ORDER BY name LIMIT 500").fetchall()];c.close()
        codes=[x for x in codes if emp_allowed(u,x)]
        cards="".join(card_html(emp(x),r) for x in codes if emp(x) and (r:=ensure_qr(u,x)) and r["status"]=="active" )
        return H.send(_tls.request,CARD_CSS+f'<div style="text-align:center"><button onclick="window.print()">🖨 طباعة {len(codes)} بطاقة</button> <a href="/id-cards.pdf?codes={quote(",".join(codes),safe=",")}">PDF</a></div><div class="cards">{cards}</div>',200,"text/html")
    def id_cards_pdf(u):
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.utils import ImageReader
        codes=[x for x in urllib.parse.parse_qs(urllib.parse.urlparse(_tls.request.path).query).get("codes",[""])[0].split(",") if x]
        if not codes:
            c=db();codes=[r["emp_code"] for r in c.execute("SELECT emp_code FROM employees WHERE status!='مؤرشف' ORDER BY name LIMIT 500").fetchall()];c.close()
        codes=[x for x in codes if emp_allowed(u,x)]
        out=io.BytesIO();cv=canvas.Canvas(out,pagesize=A4);W,HH=A4;cw,ch=242,153
        font_name="Helvetica"
        font_bold="Helvetica-Bold"
        try:
            from reportlab.pdfbase import pdfmetrics as _pm
            from reportlab.pdfbase.ttfonts import TTFont as _TT
            font_path=os.path.join(os.path.dirname(os.path.abspath(__file__)),"fonts","DejaVuSans.ttf")
            if os.path.exists(font_path):
                _pm.registerFont(_TT("HRDejaVu",font_path)); font_name=font_bold="HRDejaVu"
        except Exception: pass
        for i,code in enumerate(codes):
            e=emp(code)
            if not e:continue
            if i and i%8==0:cv.showPage()
            j=i%8;x=28+(j%2)*270;y=HH-28-ch-(j//2)*180;r=ensure_qr(u,code)
            cv.roundRect(x,y,cw,ch,10,1,0);cv.setFont(font_bold,10);cv.drawString(x+12,y+ch-24,"HR ENTERPRISE");cv.setFont(font_bold,12);cv.drawString(x+12,y+ch-58,str(e["name"])[:34]);cv.setFont(font_bold,9);cv.drawString(x+12,y+ch-74,str(code));cv.setFont(font_name,8);cv.drawString(x+12,y+ch-90,str(e["job"] or "")[:35]);cv.drawString(x+12,y+ch-104,str(e["department"] or "")[:35]);cv.drawImage(ImageReader(io.BytesIO(qr_png(r["token"]))),x+cw-82,y+12,width=65,height=65,mask="auto")
        cv.save();return H.send(_tls.request,out.getvalue(),200,"application/pdf",{"Content-Disposition":"attachment; filename=HR-Enterprise-ID-Cards.pdf"})

    def contracts_page(u):
        code=urllib.parse.parse_qs(urllib.parse.urlparse(_tls.request.path).query).get("emp_code",[""])[0]
        c=db();emps=c.execute("SELECT emp_code,name FROM employees ORDER BY name").fetchall();rows=c.execute("SELECT ct.*,e.name FROM contracts ct JOIN employees e ON e.emp_code=ct.emp_code WHERE (?='' OR ct.emp_code=?) ORDER BY ct.id DESC",(code,code)).fetchall();c.close()
        opts="".join(f'<option value="{esc(e["emp_code"])}">{esc(e["emp_code"])} — {esc(e["name"])}</option>' for e in emps if emp_allowed(u,e["emp_code"]))
        trs="".join(f'<tr><td>{esc(r["emp_code"])}</td><td>{esc(r["name"])}</td><td>{esc(r["contract_no"] or "—")}</td><td>{esc(r["contract_type"])}</td><td>{esc(r["start_date"] or "—")}</td><td>{esc(r["end_date"] or "—")}</td><td>{float(r["amount"] or 0):g}</td><td>{esc(r["status"])}</td><td><form method="post" action="/contracts/save">{csrf_field(u)}<input type="hidden" name="id" value="{r["id"]}"><input type="hidden" name="emp_code" value="{esc(r["emp_code"])}"><input type="hidden" name="action" value="renew"><button class="btn gray">تجديد</button></form></td></tr>' for r in rows if emp_allowed(u,r["emp_code"]))
        body=f"""<div class="top"><div class="title"><h1>📄 العقود</h1><p>إنشاء وتجديد وتاريخ العقود.</p></div></div>
        <div class="card"><form class="form" method="post" action="/contracts/save">{csrf_field(u)}<div class="field"><label>الموظف</label><select name="emp_code" required>{opts}</select></div><div class="field"><label>رقم العقد</label><input name="contract_no"></div><div class="field"><label>النوع</label><input name="contract_type" value="دوام كامل"></div><div class="field"><label>من</label><input type="date" name="start_date"></div><div class="field"><label>إلى</label><input type="date" name="end_date"></div><div class="field"><label>المبلغ</label><input type="number" step="0.01" name="amount"></div><div class="field full"><textarea name="notes" placeholder="ملاحظات"></textarea></div><div class="full"><button class="btn">حفظ العقد</button></div></form></div>
        <div class="card table-wrap"><table class="table"><thead><tr><th>الكود</th><th>الموظف</th><th>العقد</th><th>النوع</th><th>من</th><th>إلى</th><th>المبلغ</th><th>الحالة</th><th></th></tr></thead><tbody>{trs or '<tr><td colspan="9">لا توجد عقود</td></tr>'}</tbody></table></div>"""
        return H.send(_tls.request,page("Contracts",body,u,"contracts"))
    def contract_save(u,f):
        code=f.get("emp_code","")
        if not emp_allowed(u,code):return H.forbid(_tls.request)
        c=db()
        if f.get("action")=="renew":
            r=c.execute("SELECT * FROM contracts WHERE id=?",(f.get("id"),)).fetchone()
            if not r:c.close();return H.redirect(_tls.request,"/contracts")
            if r["status"] not in ("active", "expired", "renewed"):
                c.close(); return H.send(_tls.request,page("Contract","<div class='card'><div class='alert'>لا يمكن تجديد هذا العقد بالحالة الحالية.</div></div>",u,"contracts"),400)
            try: ns=date.fromisoformat(r["end_date"])+timedelta(days=1) if r["end_date"] else date.today()
            except Exception: ns=date.today()
            ne=ns.replace(year=ns.year+1)
            c.execute("UPDATE contracts SET status='renewed',updated_at=? WHERE id=?",(now(),r["id"]))
            c.execute("INSERT INTO contracts(emp_code,contract_no,contract_type,start_date,end_date,amount,status,notes,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(code,(r["contract_no"] or "")+"-R",r["contract_type"],ns.isoformat(),ne.isoformat(),r["amount"],"active","Renewed from #"+str(r["id"]),u["username"],now(),now()))
        else:
            sd=f.get("start_date") or "";ed=f.get("end_date") or ""
            if sd and ed and ed<sd:c.close();return H.send(_tls.request,page("Contract","<div class='card'><div class='alert'>تاريخ النهاية يجب أن يكون بعد البداية.</div></div>",u,"contracts"),400)
            st="expired" if ed and ed<date.today().isoformat() else "active"
            c.execute("INSERT INTO contracts(emp_code,contract_no,contract_type,start_date,end_date,amount,status,notes,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(code,f.get("contract_no"),f.get("contract_type") or "دوام كامل",sd,ed,float(f.get("amount") or 0),st,f.get("notes",""),u["username"],now(),now()))
        c.commit();c.close();audit(u["username"],u["role"],"CONTRACT_CHANGE","Contracts",code);return H.redirect(_tls.request,"/contracts?emp_code="+quote(code))

    def training_page(u):
        code=urllib.parse.parse_qs(urllib.parse.urlparse(_tls.request.path).query).get("emp_code",[""])[0]
        c=db();emps=c.execute("SELECT emp_code,name FROM employees ORDER BY name").fetchall();rows=c.execute("SELECT t.*,e.name FROM training_records t JOIN employees e ON e.emp_code=t.emp_code WHERE (?='' OR t.emp_code=?) ORDER BY t.id DESC",(code,code)).fetchall();c.close()
        opts="".join(f'<option value="{esc(e["emp_code"])}">{esc(e["emp_code"])} — {esc(e["name"])}</option>' for e in emps if emp_allowed(u,e["emp_code"]))
        trs="".join(f'<tr><td>{esc(r["name"])}</td><td>{esc(r["course"])}</td><td>{esc(r["provider"] or "—")}</td><td>{esc(r["start_date"] or "—")}</td><td>{esc(r["end_date"] or "—")}</td><td>{esc(r["expiry_date"] or "—")}</td><td>{esc(r["status"])}</td><td>{float(r["score"] or 0):g}</td></tr>' for r in rows if emp_allowed(u,r["emp_code"]))
        body=f"""<div class="top"><div class="title"><h1>🎓 التدريب</h1><p>برامج، شهادات، انتهاء صلاحية وتقارير.</p></div></div><div class="card"><form class="form" method="post" action="/training/save">{csrf_field(u)}<div class="field"><label>الموظف</label><select name="emp_code">{opts}</select></div><div class="field"><label>البرنامج</label><input name="course" required></div><div class="field"><label>الجهة/المدرب</label><input name="provider"></div><div class="field"><label>من</label><input type="date" name="start_date"></div><div class="field"><label>إلى</label><input type="date" name="end_date"></div><div class="field"><label>انتهاء الشهادة</label><input type="date" name="expiry_date"></div><div class="field"><label>النتيجة</label><input type="number" min="0" max="100" name="score" value="0"></div><div class="field"><label>رقم الشهادة</label><input name="certificate_no"></div><div class="full"><textarea name="notes" placeholder="ملاحظات"></textarea></div><div class="full"><button class="btn">حفظ</button></div></form></div><div class="card table-wrap"><table class="table"><thead><tr><th>الموظف</th><th>البرنامج</th><th>المدرب</th><th>من</th><th>إلى</th><th>انتهاء</th><th>الحالة</th><th>النتيجة</th></tr></thead><tbody>{trs or '<tr><td colspan="8">لا توجد سجلات</td></tr>'}</tbody></table></div>"""
        return H.send(_tls.request,page("Training",body,u,"training"))
    def training_save(u,f):
        code=f.get("emp_code","")
        if not emp_allowed(u,code):return H.forbid(_tls.request)
        score=float(f.get("score") or 0)
        if not 0<=score<=100:return H.send(_tls.request,page("Training","<div class='card'><div class='alert'>النتيجة 0..100.</div></div>",u,"training"),400)
        c=db();c.execute("INSERT INTO training_records(emp_code,course,provider,start_date,end_date,expiry_date,status,score,certificate_no,notes,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(code,f.get("course"),f.get("provider"),f.get("start_date"),f.get("end_date"),f.get("expiry_date"),"completed",score,f.get("certificate_no"),f.get("notes",""),u["username"],now(),now()));c.commit();c.close();audit(u["username"],u["role"],"TRAINING_CREATE","Training",code);return H.redirect(_tls.request,"/training?emp_code="+quote(code))

    def evaluations_page(u):
        c=db();cycles=c.execute("SELECT * FROM evaluation_cycles ORDER BY id DESC").fetchall();emps=c.execute("SELECT emp_code,name FROM employees WHERE status!='مؤرشف' ORDER BY name").fetchall();recs=c.execute("SELECT r.*,e.name,c.name cycle_name FROM evaluation_records r JOIN employees e ON e.emp_code=r.emp_code JOIN evaluation_cycles c ON c.id=r.cycle_id ORDER BY r.id DESC LIMIT 500").fetchall();c.close()
        co="".join(f'<option value="{r["id"]}">{esc(r["name"])}</option>' for r in cycles);eo="".join(f'<option value="{esc(e["emp_code"])}">{esc(e["emp_code"])} — {esc(e["name"])}</option>' for e in emps if emp_allowed(u,e["emp_code"]))
        rh=""
        for r in recs:
            if emp_allowed(u,r["emp_code"]):
                a=f'<form method="post" action="/evaluations/approve">{csrf_field(u)}<input type="hidden" name="id" value="{r["id"]}"><button class="btn ok">اعتماد</button></form>' if r["status"]=="submitted" and can(u,"evaluations.manage") else ""
                rh+=f'<tr><td>{esc(r["cycle_name"])}</td><td>{esc(r["name"])}</td><td>{float(r["score"]):g}%</td><td>{esc(r["evaluator"] or "")}</td><td>{esc(r["status"])}</td><td>{a}</td></tr>'
        body=f"""<div class="top"><div class="title"><h1>⭐ التقييمات</h1><p>دورات، معايير، نتائج، اعتماد وتاريخ.</p></div></div>
        <div class="grid g2"><div class="card"><form class="form" method="post" action="/evaluations/cycle">{csrf_field(u)}<h3>دورة جديدة</h3><input name="name" placeholder="اسم الدورة" required><input type="date" name="start_date"><input type="date" name="end_date"><button class="btn">إنشاء</button></form></div>
        <div class="card"><form class="form" method="post" action="/evaluations/save">{csrf_field(u)}<h3>تقييم</h3><select name="cycle_id" required>{co}</select><select name="emp_code" required>{eo}</select><input name="evaluator" value="{esc(u["username"])}"><input type="number" min="0" max="100" step=".01" name="score" placeholder="Score" required><textarea name="criteria_json" placeholder='attendance/productivity JSON'>{{}}</textarea><textarea name="comments"></textarea><button class="btn">حفظ وإرسال</button></form></div></div>
        <div class="card table-wrap"><table class="table"><thead><tr><th>الدورة</th><th>الموظف</th><th>النتيجة</th><th>المقيّم</th><th>الحالة</th><th></th></tr></thead><tbody>{rh or '<tr><td colspan="6">لا توجد تقييمات</td></tr>'}</tbody></table></div>"""
        return H.send(_tls.request,page("Evaluations",body,u,"evaluations"))
    def evaluation_cycle(u,f):
        c=db()
        try:c.execute("INSERT INTO evaluation_cycles(name,start_date,end_date,status,created_by,created_at) VALUES(?,?,?,?,?,?)",(f.get("name"),f.get("start_date"),f.get("end_date"),"open",u["username"],now()));c.commit()
        except Exception:c.close();return H.send(_tls.request,page("Evaluations","<div class='card'><div class='alert'>اسم الدورة موجود بالفعل.</div></div>",u,"evaluations"),400)
        c.close();return H.redirect(_tls.request,"/evaluations")
    def evaluation_save(u,f):
        code=f.get("emp_code","")
        if not emp_allowed(u,code):return H.forbid(_tls.request)
        try:s=float(f.get("score") or 0);json.loads(f.get("criteria_json") or "{}")
        except:return H.send(_tls.request,page("Evaluations","<div class='card'><div class='alert'>بيانات التقييم غير صالحة.</div></div>",u,"evaluations"),400)
        if not 0<=s<=100:return H.send(_tls.request,page("Evaluations","<div class='card'><div class='alert'>النتيجة 0..100.</div></div>",u,"evaluations"),400)
        c=db();cy=c.execute("SELECT * FROM evaluation_cycles WHERE id=?",(f.get("cycle_id"),)).fetchone()
        if not cy:c.close();return H.redirect(_tls.request,"/evaluations")
        c.execute("INSERT INTO evaluation_records(cycle_id,emp_code,evaluator,score,criteria_json,comments,status,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(cycle_id,emp_code) DO UPDATE SET evaluator=excluded.evaluator,score=excluded.score,criteria_json=excluded.criteria_json,comments=excluded.comments,status='submitted',created_by=excluded.created_by,created_at=excluded.created_at",(cy["id"],code,f.get("evaluator"),s,f.get("criteria_json") or "{}",f.get("comments",""),"submitted",u["username"],now()));c.commit();c.close();audit(u["username"],u["role"],"EVALUATION_SUBMIT","Evaluations",code);return H.redirect(_tls.request,"/evaluations")
    def evaluation_approve(u,f):
        if not can(u,"evaluations.manage"):return H.forbid(_tls.request)
        c=db();c.execute("UPDATE evaluation_records SET status='approved',approved_by=?,approved_at=? WHERE id=?",(u["username"],now(),f.get("id")));c.commit();c.close();return H.redirect(_tls.request,"/evaluations")

    old_get=H.do_GET;old_post=H.do_POST
    def get(self):
        _tls.request=self
        p=urllib.parse.urlparse(self.path).path
        if p.startswith("/qr/verify/"):
            H._verify_ip=self.client_address[0];return qr_verify(urllib.parse.unquote(p.split("/qr/verify/",1)[1]))
        if p.startswith("/qr/image/"):
            u=self.require()
            if not u:return
            code=urllib.parse.unquote(p.split("/qr/image/",1)[1])
            if not emp_allowed(u,code):return H.forbid(self)
            r=ensure_qr(u,code)
            if not r or r["status"]!="active": return H.send(self,b"QR revoked",410,"text/plain")
            return H.send(self,qr_png(r["token"]),200,"image/png",{"Cache-Control":"no-store"})
        if p.startswith("/qr/profile/"):
            u=self.require()
            if not u:return
            return qr_profile(u,urllib.parse.unquote(p.split("/qr/profile/",1)[1]))
        if p.startswith("/id-card/"):
            u=self.require()
            if not u:return
            return id_card(u,urllib.parse.unquote(p.split("/id-card/",1)[1]))
        if p=="/id-cards":
            u=self.require()
            if not u:return
            return id_cards(u)
        if p=="/id-cards.pdf":
            u=self.require()
            if not u:return
            return id_cards_pdf(u)
        if p=="/qr/scanner":
            u=self.require()
            if not u:return
            return qr_scanner(u)
        if p=="/contracts":
            u=self.require()
            if not u:return
            return contracts_page(u)
        if p=="/training":
            u=self.require()
            if not u:return
            return training_page(u)
        if p=="/evaluations":
            u=self.require()
            if not u:return
            return evaluations_page(u)
        return old_get(self)
    def post(self):
        _tls.request=self
        p=urllib.parse.urlparse(self.path).path
        if p in ("/qr/regenerate","/qr/revoke","/contracts/save","/training/save","/evaluations/cycle","/evaluations/save","/evaluations/approve"):
            u=self.require()
            if not u:return
            f=self.form()
            if f.get("_csrf")!=u.get("csrf"):return H.send(self,page("Security","<div class='card'><div class='alert'>CSRF</div></div>",u),403)
            if p=="/qr/regenerate":
                code=f.get("emp_code","")
                if not (can(u,"qr.manage") or can(u,"employees.edit")):return H.forbid(self)
                ensure_qr(u,code,True);return H.redirect(self,"/qr/profile/"+quote(code,safe=""))
            if p=="/qr/revoke":
                code=f.get("emp_code","")
                if not (can(u,"qr.manage") or can(u,"employees.edit")):return H.forbid(self)
                c=db();c.execute("UPDATE qr_identities SET status='revoked',revoked_at=?,revoked_by=? WHERE emp_code=?",(now(),u["username"],code));c.commit();c.close();audit(u["username"],u["role"],"QR_REVOKED","QR Identity",code);return H.redirect(self,"/qr/profile/"+quote(code,safe=""))
            if p=="/contracts/save":return contract_save(u,f)
            if p=="/training/save":return training_save(u,f)
            if p=="/evaluations/cycle":return evaluation_cycle(u,f)
            if p=="/evaluations/save":return evaluation_save(u,f)
            if p=="/evaluations/approve":return evaluation_approve(u,f)
        return old_post(self)
    H.do_GET=get;H.do_POST=post
    g["completion_qr_png"]=qr_png;g["completion_ensure_qr"]=ensure_qr

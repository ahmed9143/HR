import os, tempfile, subprocess, time, urllib.request, urllib.parse, http.cookiejar, sqlite3, sys, pathlib
try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception: pass
ROOT=pathlib.Path(__file__).resolve().parent
with tempfile.TemporaryDirectory(prefix='hr_enterprise_') as td:
    env=os.environ.copy(); env.update(HR_DATA_DIR=td,HR_BOOTSTRAP_PASSWORD='TestAdmin@12345',HR_PORT='8971',HR_PORT_MAX='8980',HR_NO_BROWSER='1',HR_MODE='standalone')
    p=subprocess.Popen([sys.executable,'server.py'],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    try:
        for _ in range(50):
            try:
                h=urllib.request.urlopen('http://127.0.0.1:8971/health',timeout=1).read().decode('utf-8'); assert '"ok": true' in h; break
            except Exception: time.sleep(.2)
        else: raise AssertionError('health failed')
        c=sqlite3.connect(pathlib.Path(td)/'hr_central.db'); c.execute("UPDATE users SET must_change_password=0 WHERE username='admin'"); c.execute("INSERT INTO employees(emp_code,name,department,job,status) VALUES('Q100','أحمد محمد','HR','Manager','على رأس العمل')"); c.commit(); c.close()
        jar=http.cookiejar.CookieJar(); op=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        op.open(urllib.request.Request('http://127.0.0.1:8971/login',data=urllib.parse.urlencode({'username':'admin','password':'TestAdmin@12345'}).encode(),method='POST'))
        prof=op.open('http://127.0.0.1:8971/employee/profile/Q100').read().decode('utf-8'); assert 'الهوية الرقمية' in prof and 'طباعة البطاقة' in prof
        csrf=prof.split('name="_csrf" value="',1)[1].split('"',1)[0]
        def post(path, data):
            return op.open(urllib.request.Request('http://127.0.0.1:8971'+path,data=urllib.parse.urlencode(data).encode(),method='POST'))
        post('/qr/generate',{'_csrf':csrf,'emp_code':'Q100'})
        # Branding must never delete QR assets. Upload a tiny real PNG through the admin UI.
        import base64
        tiny_png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=')
        def multipart_post(path, fields, filename, data, ctype='image/png'):
            boundary='----HRTestBoundary'
            chunks=[]
            for k,v in fields.items(): chunks += [f'--{boundary}\r\n'.encode(),f'Content-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()]
            chunks += [f'--{boundary}\r\n'.encode(),f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: {ctype}\r\n\r\n'.encode(),data,b'\r\n',f'--{boundary}--\r\n'.encode()]
            req=urllib.request.Request('http://127.0.0.1:8971'+path,data=b''.join(chunks),headers={'Content-Type':f'multipart/form-data; boundary={boundary}'},method='POST')
            return op.open(req)
        multipart_post('/branding/logo',{'_csrf':csrf},'logo.png',tiny_png)
        assert op.open('http://127.0.0.1:8971/qr/image/Q100').read().startswith(b'\x89PNG'), 'logo upload destroyed QR asset'
        multipart_post('/employee/photo/upload',{'_csrf':csrf,'emp_code':'Q100'},'profile.png',tiny_png)
        # PHASE 1 PERF FIX: uploads are now re-encoded to a size-capped JPEG at
        # upload time (see enterprise_completion.py), so the stored/served bytes
        # are JPEG regardless of the original format uploaded.
        assert op.open('http://127.0.0.1:8971/employee/photo/Q100').read().startswith(b'\xff\xd8\xff')
        prof2=op.open('http://127.0.0.1:8971/employee/profile/Q100').read().decode('utf-8'); assert '/employee/photo/Q100' in prof2
        png=op.open('http://127.0.0.1:8971/qr/image/Q100').read(); assert png.startswith(b'\x89PNG')
        from PIL import Image
        from pyzbar.pyzbar import decode
        import io
        decoded=decode(Image.open(io.BytesIO(png))); assert decoded and b'/qr/verify/' in decoded[0].data
        token=decoded[0].data.decode().rsplit('/qr/verify/',1)[1]
        public=urllib.request.build_opener(); verify_url='http://127.0.0.1:8971/qr/verify/'+token; assert 'VALID' in public.open(verify_url).read().decode('utf-8'); assert token
        vr=op.open('http://127.0.0.1:8971/qr/verify/'+urllib.parse.quote(token)).read().decode('utf-8'); assert 'Q100' in vr and 'VALID' in vr
        post('/qr/regenerate',{'_csrf':csrf,'emp_code':'Q100'}); png2=op.open('http://127.0.0.1:8971/qr/image/Q100').read(); decoded2=decode(Image.open(io.BytesIO(png2))); token2=decoded2[0].data.decode().rsplit('/qr/verify/',1)[1]; assert token2!=token
        try: op.open('http://127.0.0.1:8971/qr/verify/'+urllib.parse.quote(token)); raise AssertionError('old token accepted')
        except urllib.error.HTTPError as e: assert e.code==404
        post('/qr/revoke',{'_csrf':csrf,'emp_code':'Q100'})
        vr2=op.open('http://127.0.0.1:8971/qr/verify/'+urllib.parse.quote(token2)).read().decode('utf-8'); assert 'REVOKED' in vr2
        assert op.open('http://127.0.0.1:8971/id-card/Q100').status==200
        assert op.open('http://127.0.0.1:8971/contracts').status==200
        assert op.open('http://127.0.0.1:8971/training').status==200
        c=sqlite3.connect(pathlib.Path(td)/'hr_central.db'); assert c.execute("select count(*) from audit where action in ('QR_CREATED','QR_REGENERATED','QR_REVOKED','QR_VERIFIED')").fetchone()[0]>=4; assert c.execute("select image_path from qr_identities where emp_code='Q100'").fetchone()[0]; c.close()
        print('ENTERPRISE STABLE TEST: PASS')
    finally:
        p.terminate(); p.wait(timeout=5)

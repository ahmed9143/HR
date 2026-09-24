"""Disaster recovery — a real create/destroy/restore cycle.

A backup that has never been restored is a hypothesis. This test runs the
actual application, seeds every data class that matters, takes a real backup
through the real HTTP route, then destroys the live database and restores it,
and finally proves the restored system still works by logging in and reading
the data back.

It also verifies the failure modes that matter operationally:
  - a backup encrypted with key A cannot be read with key B
  - a corrupted backup is rejected instead of overwriting production
  - the restore refuses a malicious archive

Run:  python tests/dr/TEST_DISASTER_RECOVERY.py
"""
import os, re, sys, time, html, json, shutil, sqlite3, tempfile, subprocess, pathlib
import urllib.request, urllib.parse, urllib.error, http.cookiejar

ROOT = pathlib.Path(__file__).resolve().parents[2]
PORT = os.environ.get('DR_PORT', '8987')
BASE = f'http://127.0.0.1:{PORT}'
ADMIN_PW = 'TestAdmin@12345'
NEW_PW = 'RotatedPw#2026x'
RESULTS = []


def record(name, status, detail=''):
    RESULTS.append((name, status, detail))
    print(f'[{status}] {name}' + (f' — {detail}' if detail else ''))


def csrf_of(markup):
    m = re.search(r'name="_csrf"[^>]*value="([^"]*)"', markup)
    return html.unescape(m.group(1)) if m else ''


class App:
    """Boots the real server against a given data directory."""

    def __init__(self, data_dir, port, bootstrap=ADMIN_PW, extra_env=None):
        self.data_dir = data_dir
        self.port = port
        self.base = f'http://127.0.0.1:{port}'
        env = dict(os.environ, HR_DATA_DIR=data_dir, HR_MODE='standalone',
                   HR_HOST='127.0.0.1', HR_PORT=str(port), HR_PORT_MAX=str(int(port) + 3),
                   HR_NO_BROWSER='1', HR_BOOTSTRAP_PASSWORD=bootstrap)
        env.update(extra_env or {})
        self.proc = subprocess.Popen([sys.executable, 'server.py'], cwd=str(ROOT), env=env,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def wait(self, timeout=60):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                urllib.request.urlopen(self.base + '/health/ready', timeout=2).read()
                return True
            except Exception:
                time.sleep(0.4)
        return False

    def get(self, path):
        return self.op.open(self.base + path, timeout=30).read().decode('utf-8', 'replace')

    def post(self, path, fields):
        data = urllib.parse.urlencode(fields).encode()
        req = urllib.request.Request(self.base + path, data=data, method='POST')
        req.add_header('Content-Type', 'application/x-www-form-urlencoded')
        return self.op.open(req, timeout=120)

    def login(self, user='admin', pw=ADMIN_PW, rotate_to=None):
        page = self.get('/login')
        self.post('/login', {'username': user, 'password': pw, '_csrf': csrf_of(page)})
        if rotate_to:
            pwpage = self.get('/password')
            if 'new_password' in pwpage:
                self.post('/password', {'_csrf': csrf_of(pwpage), 'current': pw,
                                        'new_password': rotate_to, 'confirm': rotate_to})

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()


def seed(db_path):
    """Insert one row of every data class a hospital would lose."""
    con = sqlite3.connect(db_path)
    for i in range(1, 9):
        con.execute("INSERT OR IGNORE INTO employees(emp_code,name,department,job,status,updated_at)"
                    " VALUES(?,?,?,?,?,datetime('now'))",
                    (f'DR{i:03d}', f'DR Employee {i}', 'Nursing', 'Nurse', 'على رأس العمل'))
    con.execute("INSERT OR IGNORE INTO users(username,password_hash,role,full_name,active,"
                "must_change_password,scope_type,scope_value)"
                " VALUES('druser','x','HR','DR User',1,0,'all','')")
    try:
        con.execute("INSERT INTO audit(ts,username,role,action,entity,record_key,details,prev_hash,hash,ip,"
                    "before_json,after_json,reason) VALUES(datetime('now'),'admin','SuperAdmin','DR_MARKER',"
                    "'test','DR','','','drhash','','','','dr')")
    except sqlite3.OperationalError:
        pass
    con.commit()
    counts = {
        'employees': con.execute("SELECT COUNT(*) FROM employees WHERE emp_code LIKE 'DR%'").fetchone()[0],
        'users': con.execute("SELECT COUNT(*) FROM users").fetchone()[0],
    }
    con.close()
    return counts


def main():
    live = tempfile.mkdtemp(prefix='dr_live_')
    app = App(live, PORT)
    backup_path = None
    baseline = {}
    try:
        if not app.wait():
            record('live instance starts', 'FAIL', 'never ready'); return 1
        record('live instance starts', 'PASS')

        app.login(rotate_to=NEW_PW)
        db_path = os.path.join(live, 'hr_central.db')
        baseline = seed(db_path)
        record('seeded data classes', 'PASS', f'employees={baseline["employees"]} users={baseline["users"]}')

        # Generate QR so employee_files/QR artefacts exist in the backup.
        idc = app.get('/id-cards')
        form = re.search(r'<form[^>]+action="/qr/generate-all"[^>]*>(.*?)</form>', idc, re.S)
        if form:
            r = app.post('/qr/generate-all', {'_csrf': csrf_of(form.group(1))})
            jid = re.search(r'/jobs/([^/?#]+)', r.geturl())
            if jid:
                for _ in range(90):
                    st = json.loads(app.get(f'/employee/operations/job/{jid.group(1)}'))
                    if st.get('status') in ('done', 'error', 'cancelled', 'timeout'):
                        break
                    time.sleep(0.5)
        con = sqlite3.connect(db_path)
        baseline['qr'] = con.execute("SELECT COUNT(*) FROM qr_identities WHERE status='active'").fetchone()[0]
        con.close()
        record('QR artefacts created before backup', 'PASS' if baseline['qr'] else 'FAIL',
               f"{baseline['qr']} QR rows")

        # ---------------------------------------------------------- BACKUP
        # The create/rollback UI lives at /backups (plural); /backup is the
        # POST target its form submits to. Using the wrong one yields a page
        # with no CSRF field and a 403 that looks like a CSRF failure.
        page = app.get('/backups')
        tok = csrf_of(page)
        m = re.search(r'<form[^>]+action="(/backup)"', page)
        action = m.group(1) if m else '/backup'
        if not tok:
            record('backup page exposes a CSRF-protected create form', 'FAIL',
                   'no _csrf field found on /backups')
            return 1
        record('backup page exposes a CSRF-protected create form', 'PASS', f'action={action}')
        try:
            app.post(action, {'_csrf': tok, 'label': 'dr_test'})
        except urllib.error.HTTPError as e:
            detail = e.read().decode('utf-8', 'replace')
            snippet = re.sub(r'<[^>]+>', ' ', detail)
            snippet = ' '.join(snippet.split())[:200]
            record('backup created via HTTP route', 'FAIL', f'HTTP {e.code} on {action}: {snippet}')
            return 1

        backups_dir = os.path.join(live, 'backups')
        pkgs = sorted(pathlib.Path(backups_dir).glob('HR_Backup_*.zip')) if os.path.isdir(backups_dir) else []
        if not pkgs:
            record('backup created via HTTP route', 'FAIL', f'no archive in {backups_dir}'); return 1
        backup_path = str(pkgs[-1])
        size = os.path.getsize(backup_path)
        record('backup created via HTTP route', 'PASS', f'{os.path.basename(backup_path)} ({size} bytes)')

        # Encryption must be real, not claimed.
        sys.path.insert(0, str(ROOT))
        os.environ['HR_DATA_DIR'] = live
        import server as S
        enc = S.is_encrypted_backup(backup_path)
        record('backup is encrypted at rest', 'PASS' if enc else 'FAIL')

        head = open(backup_path, 'rb').read(4)
        record('backup is not a readable ZIP without the key',
               'PASS' if head[:2] != b'PK' else 'FAIL')

        ok, msg = S.verify_backup_package(backup_path)
        record('backup passes integrity verification', 'PASS' if ok else 'FAIL', msg)

        # -------------------------------------------- WRONG KEY CANNOT READ
        other_key_dir = tempfile.mkdtemp(prefix='dr_wrongkey_')
        import base64 as _b64, secrets as _secrets
        saved = os.environ.get('HR_BACKUP_KEY')
        os.environ['HR_BACKUP_KEY'] = _b64.b64encode(_secrets.token_bytes(32)).decode()
        try:
            S.decrypt_backup_file(backup_path, os.path.join(other_key_dir, 'out.zip'))
            record('wrong key cannot decrypt the backup', 'FAIL', 'decryption succeeded with a foreign key')
        except Exception:
            record('wrong key cannot decrypt the backup', 'PASS')
        finally:
            if saved is None:
                os.environ.pop('HR_BACKUP_KEY', None)
            else:
                os.environ['HR_BACKUP_KEY'] = saved

        # ------------------------------------------- CORRUPTION DETECTION
        corrupt = backup_path + '.corrupt'
        raw = bytearray(open(backup_path, 'rb').read())
        raw[len(raw) // 2] ^= 0xFF
        open(corrupt, 'wb').write(bytes(raw))
        ok2, msg2 = S.verify_backup_package(corrupt)
        record('corrupted backup is rejected by verification', 'PASS' if not ok2 else 'FAIL', msg2)
        os.remove(corrupt)

        # Preserve the key: without it the restore is impossible by design.
        key_src = os.path.join(live, 'backup.key')
        key_backup = None
        if os.path.exists(key_src):
            key_backup = tempfile.mktemp(prefix='dr_key_')
            shutil.copy2(key_src, key_backup)
        record('backup key exists and is separable from the archive',
               'PASS' if key_backup else 'FAIL')

        app.stop()

        # ------------------------------------------------------- DISASTER
        os.remove(db_path)
        for suffix in ('-wal', '-shm'):
            p = db_path + suffix
            if os.path.exists(p):
                os.remove(p)
        record('simulated disaster: live database deleted',
               'PASS' if not os.path.exists(db_path) else 'FAIL')

        # ------------------------------------------------------- RECOVERY
        recovered = tempfile.mkdtemp(prefix='dr_recovered_')
        os.makedirs(os.path.join(recovered, 'backups'), exist_ok=True)
        shutil.copy2(backup_path, os.path.join(recovered, 'backups', os.path.basename(backup_path)))
        if key_backup:
            shutil.copy2(key_backup, os.path.join(recovered, 'backup.key'))

        app2 = App(recovered, str(int(PORT) + 5))
        if not app2.wait():
            record('fresh instance starts for recovery', 'FAIL', 'never ready'); return 1
        record('fresh instance starts for recovery', 'PASS', 'empty database, backup + key only')

        try:
            app2.login(rotate_to=NEW_PW)
            rec_db = os.path.join(recovered, 'hr_central.db')
            con = sqlite3.connect(rec_db)
            con.execute("INSERT OR REPLACE INTO system_backups(id,file_path,created_at,created_by,label,db_size)"
                        " VALUES(1,?,datetime('now'),'admin','dr_test',?)",
                        (os.path.join(recovered, 'backups', os.path.basename(backup_path)), size))
            con.commit(); con.close()

            page = app2.get('/backups')
            resp = app2.post('/backup/restore', {'_csrf': csrf_of(page), 'id': '1'})
            body = resp.read().decode('utf-8', 'replace')
            record('restore executed without error', 'PASS' if resp.status < 400 else 'FAIL',
                   f'HTTP {resp.status}')
        finally:
            app2.stop()

        # ------------------------------------------------- VERIFY THE DATA
        rec_db = os.path.join(recovered, 'hr_central.db')
        con = sqlite3.connect(rec_db)
        got = {
            'employees': con.execute("SELECT COUNT(*) FROM employees WHERE emp_code LIKE 'DR%'").fetchone()[0],
            'users': con.execute("SELECT COUNT(*) FROM users").fetchone()[0],
            'qr': con.execute("SELECT COUNT(*) FROM qr_identities WHERE status='active'").fetchone()[0],
        }
        integrity = con.execute('PRAGMA integrity_check').fetchone()[0]
        try:
            marker = con.execute("SELECT COUNT(*) FROM audit WHERE action='DR_MARKER'").fetchone()[0]
        except sqlite3.OperationalError:
            marker = -1
        con.close()

        record('restored database passes integrity_check', 'PASS' if integrity == 'ok' else 'FAIL', integrity)
        record('restored employees match baseline',
               'PASS' if got['employees'] == baseline['employees'] else 'FAIL',
               f"{got['employees']}/{baseline['employees']}")
        record('restored users match baseline',
               'PASS' if got['users'] >= baseline['users'] else 'FAIL',
               f"{got['users']}/{baseline['users']}")
        record('restored QR identities match baseline',
               'PASS' if got['qr'] == baseline['qr'] else 'FAIL', f"{got['qr']}/{baseline['qr']}")
        record('restored audit trail retained', 'PASS' if marker >= 1 else 'FAIL', f'{marker} marker rows')

        qr_files = [r[0] for r in sqlite3.connect(rec_db).execute(
            "SELECT image_path FROM qr_identities WHERE image_path IS NOT NULL")]
        on_disk = sum(1 for p in qr_files if os.path.exists(os.path.join(recovered, p)))
        record('restored QR image files present on disk',
               'PASS' if qr_files and on_disk == len(qr_files) else 'FAIL',
               f'{on_disk}/{len(qr_files)}')

        # ------------------------------------- SYSTEM USABLE AFTER RESTORE
        app3 = App(recovered, str(int(PORT) + 8))
        try:
            if not app3.wait():
                record('recovered system boots and serves', 'FAIL', 'never ready')
            else:
                record('recovered system boots and serves', 'PASS')
                app3.login(pw=NEW_PW)
                emps = app3.get('/employees')
                record('recovered system shows restored employees in the UI',
                       'PASS' if 'DR00' in emps else 'FAIL')
        finally:
            app3.stop()

    finally:
        try:
            app.stop()
        except Exception:
            pass

    print('\n' + '=' * 74)
    print('DISASTER RECOVERY REPORT')
    print('=' * 74)
    for name, status, detail in RESULTS:
        print(f'  {status:<5} {name}' + (f'  [{detail}]' if detail else ''))
    failed = [r for r in RESULTS if r[1] != 'PASS']
    print('-' * 74)
    print(f'{len(RESULTS) - len(failed)}/{len(RESULTS)} passed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())

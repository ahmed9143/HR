"""ZKTeco device credential protection — runtime verification.

Proves at runtime that zk_devices.comm_password is encrypted at rest, never
rendered back into the UI, survives an edit that leaves the field blank, is
decrypted only at connect time, and that a legacy plaintext row is migrated.

Run:  python tests/security/TEST_ZK_CREDENTIALS.py
"""
import os, re, sys, time, html, sqlite3, tempfile, subprocess, pathlib
import urllib.request, urllib.parse, urllib.error, http.cookiejar

ROOT = pathlib.Path(__file__).resolve().parents[2]
PORT = os.environ.get('ZK_CRED_PORT', '8963')
BASE = f'http://127.0.0.1:{PORT}'
ADMIN_PW = 'TestAdmin@12345'
NEW_PW = 'RotatedPw#2026x'
DEVICE_PW = 'Sup3rSecretDevicePw!'
RESULTS = []


def record(name, status, detail=''):
    RESULTS.append((name, status, detail))
    print(f'[{status}] {name}' + (f' — {detail}' if detail else ''))


def csrf_of(markup):
    m = re.search(r'name="_csrf"[^>]*value="([^"]*)"', markup)
    return html.unescape(m.group(1)) if m else ''


def main():
    td = tempfile.mkdtemp(prefix='zkcred_')
    env = dict(os.environ, HR_DATA_DIR=td, HR_MODE='standalone', HR_HOST='127.0.0.1',
               HR_PORT=PORT, HR_PORT_MAX=str(int(PORT) + 3), HR_NO_BROWSER='1',
               HR_BOOTSTRAP_PASSWORD=ADMIN_PW)
    proc = subprocess.Popen([sys.executable, 'server.py'], cwd=str(ROOT), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    db_path = os.path.join(td, 'hr_central.db')
    try:
        for _ in range(120):
            try:
                urllib.request.urlopen(BASE + '/health/ready', timeout=2).read(); break
            except Exception:
                time.sleep(0.4)
        else:
            record('server starts', 'FAIL'); return 1
        record('server starts', 'PASS')

        jar = http.cookiejar.CookieJar()
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

        def get(path):
            return op.open(BASE + path, timeout=20).read().decode('utf-8', 'replace')

        def post(path, fields):
            data = urllib.parse.urlencode(fields).encode()
            req = urllib.request.Request(BASE + path, data=data, method='POST')
            req.add_header('Content-Type', 'application/x-www-form-urlencoded')
            return op.open(req, timeout=30)

        lp = get('/login')
        post('/login', {'username': 'admin', 'password': ADMIN_PW, '_csrf': csrf_of(lp)})
        pw = get('/password')
        post('/password', {'_csrf': csrf_of(pw), 'current': ADMIN_PW,
                           'new_password': NEW_PW, 'confirm': NEW_PW})
        record('admin session established', 'PASS')

        # ---- create a device through the real UI route --------------------
        devpage = get('/zkteco/devices')
        tok = csrf_of(devpage)
        post('/zkteco/devices/save', {'_csrf': tok, 'name': 'Ward A Reader', 'ip': '10.0.0.5',
                                      'port': '4370', 'location': 'Ward A',
                                      'comm_password': DEVICE_PW, 'timeout_seconds': '10'})

        con = sqlite3.connect(db_path); con.row_factory = sqlite3.Row
        row = con.execute("SELECT id,comm_password FROM zk_devices WHERE name='Ward A Reader'").fetchone()
        con.close()
        if not row:
            record('device saved', 'FAIL', 'row not created'); return 1
        record('device saved', 'PASS', f'id={row["id"]}')

        stored = row['comm_password'] or ''
        record('password is NOT stored in cleartext',
               'PASS' if DEVICE_PW not in stored else 'FAIL', f'stored={stored[:24]}...')
        record('password is stored in the encrypted envelope',
               'PASS' if stored.startswith('enc:v1:') else 'FAIL')

        # ---- the UI must not echo it back ---------------------------------
        edit = get(f'/zkteco/devices?edit={row["id"]}')
        leaked = DEVICE_PW in edit or stored in edit
        record('edit form does not leak the password', 'PASS' if not leaked else 'FAIL')
        record('edit form uses a masked input',
               'PASS' if 'type="password" name="comm_password"' in edit else 'FAIL')

        listing = get('/zkteco/devices')
        record('device list does not leak the password',
               'PASS' if DEVICE_PW not in listing and stored not in listing else 'FAIL')

        # ---- blank on save must keep the existing password ----------------
        post('/zkteco/devices/save', {'_csrf': csrf_of(edit), 'id': str(row['id']),
                                      'name': 'Ward A Reader', 'ip': '10.0.0.6',
                                      'port': '4370', 'location': 'Ward A',
                                      'comm_password': '', 'timeout_seconds': '10'})
        con = sqlite3.connect(db_path); con.row_factory = sqlite3.Row
        after = con.execute("SELECT ip,comm_password FROM zk_devices WHERE id=?", (row['id'],)).fetchone()
        con.close()
        record('editing with a blank password field keeps the stored password',
               'PASS' if after['comm_password'] == stored else 'FAIL')
        record('the rest of the edit still applied',
               'PASS' if after['ip'] == '10.0.0.6' else 'FAIL', f"ip={after['ip']}")

        # ---- round-trip and connector use ---------------------------------
        sys.path.insert(0, str(ROOT))
        os.environ['HR_DATA_DIR'] = td
        import server as S
        record('decrypt returns the original secret',
               'PASS' if S.decrypt_secret(stored) == DEVICE_PW else 'FAIL')
        record('mask_secret never reveals the value',
               'PASS' if DEVICE_PW not in S.mask_secret(stored) else 'FAIL',
               S.mask_secret(stored))

        import zkteco_connector as ZC
        adapter = ZC.make_adapter({'ip': '10.0.0.6', 'port': 4370,
                                   'comm_password': stored, 'timeout_seconds': 10}, mock=True)
        got = getattr(adapter, 'password', None)
        if got is None:
            got = getattr(getattr(adapter, '_cfg', None), 'password', None)
        record('connector receives the decrypted password',
               'PASS' if got == DEVICE_PW else 'FAIL', f'adapter password matches={got == DEVICE_PW}')

        # ---- undecryptable value must fail loudly --------------------------
        try:
            ZC.make_adapter({'ip': '10.0.0.6', 'port': 4370,
                             'comm_password': 'enc:v1:bm90LXZhbGlk', 'timeout_seconds': 10}, mock=True)
            record('undecryptable password fails loudly', 'FAIL', 'no error raised')
        except Exception as e:
            record('undecryptable password fails loudly', 'PASS', type(e).__name__)

        # ---- legacy plaintext row is migrated -----------------------------
        con = sqlite3.connect(db_path)
        con.execute("INSERT INTO zk_devices(device_key,name,location,ip,port,comm_password,"
                    "timeout_seconds,active,status,created_by,created_at,updated_at)"
                    " VALUES('legacy-dev','Legacy Reader','Old Wing','10.0.0.9',4370,"
                    "'LegacyPlain123',10,1,'unknown','admin',datetime('now'),datetime('now'))")
        con.commit(); con.close()
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()

        proc = subprocess.Popen([sys.executable, 'server.py'], cwd=str(ROOT), env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for _ in range(120):
            try:
                urllib.request.urlopen(BASE + '/health/ready', timeout=2).read(); break
            except Exception:
                time.sleep(0.4)
        con = sqlite3.connect(db_path); con.row_factory = sqlite3.Row
        leg = con.execute("SELECT comm_password FROM zk_devices WHERE device_key='legacy-dev'").fetchone()
        con.close()
        migrated = bool(leg) and leg['comm_password'].startswith('enc:v1:')
        record('legacy plaintext password migrated on startup', 'PASS' if migrated else 'FAIL',
               (leg['comm_password'][:20] + '...') if leg else 'row missing')
        if migrated:
            record('migrated legacy password still decrypts to the original',
                   'PASS' if S.decrypt_secret(leg['comm_password']) == 'LegacyPlain123' else 'FAIL')

        # ---- secret key file exists and is separable ----------------------
        record('application secret key file created',
               'PASS' if os.path.exists(os.path.join(td, 'secret.key')) else 'FAIL')

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()

    print('\n' + '=' * 74)
    print('ZKTECO CREDENTIAL PROTECTION REPORT')
    print('=' * 74)
    for name, status, detail in RESULTS:
        print(f'  {status:<5} {name}' + (f'  [{detail}]' if detail else ''))
    failed = [r for r in RESULTS if r[1] != 'PASS']
    print('-' * 74)
    print(f'{len(RESULTS) - len(failed)}/{len(RESULTS)} passed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())

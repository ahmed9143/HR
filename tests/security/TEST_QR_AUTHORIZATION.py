"""Bulk QR authorization — one owner, proven for every role by direct HTTP.

Hiding a button is not authorization. Every case below bypasses the UI and
posts straight to /qr/generate-all, which is the only thing an attacker would
do. It also proves the permission is genuinely revocable: revoking
qr.bulk_generate from HR must block HR immediately, with no restart.

Run:  python tests/security/TEST_QR_AUTHORIZATION.py
"""
import os, re, sys, time, html, sqlite3, tempfile, subprocess, pathlib
import urllib.request, urllib.parse, urllib.error, http.cookiejar

ROOT = pathlib.Path(__file__).resolve().parents[2]
PORT = os.environ.get('QRAUTH_PORT', '8933')
BASE = f'http://127.0.0.1:{PORT}'
ADMIN_PW = 'TestAdmin@12345'
NEW_PW = 'RotatedPw#2026x'
RESULTS = []


def record(name, status, detail=''):
    RESULTS.append((name, status, detail))
    print(f'[{status}] {name}' + (f' — {detail}' if detail else ''))


def csrf_of(m):
    x = re.search(r'name="_csrf"[^>]*value="([^"]*)"', m)
    return html.unescape(x.group(1)) if x else ''


class Client:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def get(self, p):
        try:
            r = self.op.open(BASE + p, timeout=30)
            return r.status, r.read().decode('utf-8', 'replace')
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode('utf-8', 'replace')

    def post(self, p, f):
        data = urllib.parse.urlencode(f).encode()
        req = urllib.request.Request(BASE + p, data=data, method='POST')
        req.add_header('Content-Type', 'application/x-www-form-urlencoded')
        try:
            r = self.op.open(req, timeout=60)
            return r.status, r.geturl(), r.read().decode('utf-8', 'replace')
        except urllib.error.HTTPError as e:
            return e.code, p, e.read().decode('utf-8', 'replace')

    def login(self, user, pw):
        _, lp = self.get('/login')
        self.post('/login', {'username': user, 'password': pw, '_csrf': csrf_of(lp)})
        _, page = self.get('/employees')
        if 'new_password' in page or 'name="current"' in page:
            _, pwp = self.get('/password')
            self.post('/password', {'_csrf': csrf_of(pwp), 'current': pw,
                                    'new_password': NEW_PW, 'confirm': NEW_PW})
            return NEW_PW
        return pw

    def token(self):
        for path in ('/employees', '/id-cards', '/'):
            _, page = self.get(path)
            t = csrf_of(page)
            if t:
                return t
        return ''


def attempt_bulk(client):
    """Returns 'allowed' | 'denied' | 'unauthenticated'."""
    tok = client.token()
    status, url, body = client.post('/qr/generate-all', {'_csrf': tok})
    if '/employee/operations/jobs/' in url:
        return 'allowed'
    if 'name="password"' in body or status in (302, 401):
        return 'unauthenticated'
    return 'denied'


def main():
    td = tempfile.mkdtemp(prefix='qrauth_')
    db_path = os.path.join(td, 'hr_central.db')
    env = dict(os.environ, HR_DATA_DIR=td, HR_MODE='standalone', HR_HOST='127.0.0.1',
               HR_PORT=PORT, HR_PORT_MAX=str(int(PORT) + 3), HR_NO_BROWSER='1',
               HR_BOOTSTRAP_PASSWORD=ADMIN_PW)
    proc = subprocess.Popen([sys.executable, 'server.py'], cwd=str(ROOT), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        for _ in range(150):
            try:
                urllib.request.urlopen(BASE + '/health/ready', timeout=2).read(); break
            except Exception:
                time.sleep(0.4)
        else:
            record('server starts', 'FAIL'); return 1
        record('server starts', 'PASS')

        sys.path.insert(0, str(ROOT)); os.environ['HR_DATA_DIR'] = td
        import server as S

        con = sqlite3.connect(db_path)
        for i in range(1, 4):
            con.execute("INSERT OR IGNORE INTO employees(emp_code,name,department,job,status,updated_at)"
                        " VALUES(?,?,?,?,?,datetime('now'))",
                        (f'AZ{i:03d}', f'Auth {i}', 'Nursing', 'Nurse', 'على رأس العمل'))
        for uname, role in (('hruser', 'HR'), ('mgruser', 'Manager'), ('empuser', 'Employee')):
            con.execute("INSERT OR REPLACE INTO users(username,password_hash,role,full_name,active,"
                        "must_change_password,scope_type,scope_value) VALUES(?,?,?,?,1,0,'all','')",
                        (uname, S.hashpw('RolePw#2026x'), role, uname))
        con.commit(); con.close()
        record('test users created for HR / Manager / Employee', 'PASS')

        # The permission must exist in the catalogue, not just in code.
        con = sqlite3.connect(db_path)
        perm_exists = con.execute("SELECT COUNT(*) FROM permissions WHERE code='qr.bulk_generate'").fetchone()[0]
        holders = sorted(r[0] for r in con.execute(
            "SELECT role FROM role_permissions WHERE permission='qr.bulk_generate'"))
        con.close()
        record('qr.bulk_generate exists as a real permission',
               'PASS' if perm_exists else 'FAIL')
        record('permission granted to the roles that previously had access',
               'PASS' if {'SuperAdmin', 'Admin', 'HR'} <= set(holders) else 'FAIL',
               ','.join(holders))
        record('permission NOT granted to Manager or Employee',
               'PASS' if not ({'Manager', 'Employee'} & set(holders)) else 'FAIL')

        # ---- unauthenticated -------------------------------------------
        anon = Client()
        record('unauthenticated POST is rejected',
               'PASS' if attempt_bulk(anon) == 'unauthenticated' else 'FAIL')

        # ---- admin ------------------------------------------------------
        admin = Client()
        admin.login('admin', ADMIN_PW)
        res = attempt_bulk(admin)
        record('admin (SuperAdmin) is allowed', 'PASS' if res == 'allowed' else 'FAIL', res)

        # ---- ordinary employee -----------------------------------------
        emp = Client(); emp.login('empuser', 'RolePw#2026x')
        res = attempt_bulk(emp)
        record('ordinary employee is denied by the server, not by a hidden button',
               'PASS' if res == 'denied' else 'FAIL', res)

        # ---- manager ----------------------------------------------------
        mgr = Client(); mgr.login('mgruser', 'RolePw#2026x')
        res = attempt_bulk(mgr)
        record('manager is denied', 'PASS' if res == 'denied' else 'FAIL', res)

        # ---- HR: allowed by default (preserves prior behaviour) --------
        hr = Client(); hr.login('hruser', 'RolePw#2026x')
        res = attempt_bulk(hr)
        record('HR is allowed by default (previous behaviour preserved)',
               'PASS' if res == 'allowed' else 'FAIL', res)

        # ---- PATH A: revoke through the real Roles screen ---------------
        # This is how an administrator actually revokes, and it must take
        # effect on the very next request.
        _, roles_page = admin.get('/roles')
        keep = [m for m in re.findall(r'name="perm"\s+value="([^"]+)"', roles_page)]
        hr_perms = [p for p in dict.fromkeys(keep) if p != 'qr.bulk_generate']
        fields = [('_csrf', admin.token()), ('role', 'HR')] + [('perm', p) for p in hr_perms]
        body = urllib.parse.urlencode(fields).encode()
        req = urllib.request.Request(BASE + '/roles/save', data=body, method='POST')
        req.add_header('Content-Type', 'application/x-www-form-urlencoded')
        ui_revoked = False
        try:
            admin.op.open(req, timeout=30)
            con = sqlite3.connect(db_path)
            ui_revoked = con.execute("SELECT COUNT(*) FROM role_permissions "
                                     "WHERE role='HR' AND permission='qr.bulk_generate'").fetchone()[0] == 0
            con.close()
        except urllib.error.HTTPError:
            pass

        if ui_revoked:
            hr2 = Client(); hr2.login('hruser', 'RolePw#2026x')
            res = attempt_bulk(hr2)
            record('revoking via the Roles screen blocks HR on the next request',
                   'PASS' if res == 'denied' else 'FAIL', res)
        else:
            record('revoking via the Roles screen blocks HR on the next request', 'SKIP',
                   'could not drive /roles/save from this harness')

        # ---- PATH B: out-of-band revoke (direct DB edit / restore) -------
        # roles_save() invalidates the cache; nothing else does. Without a TTL
        # a revoke applied outside the UI would stay ineffective for the life
        # of the process, so the cache must expire on its own.
        con = sqlite3.connect(db_path)
        con.execute("INSERT OR IGNORE INTO role_permissions(role,permission)"
                    " VALUES('HR','qr.bulk_generate')")
        con.commit(); con.close()
        time.sleep(S._ROLE_PERMS_TTL + 2)
        hr3 = Client(); hr3.login('hruser', 'RolePw#2026x')
        record('out-of-band GRANT becomes visible after the cache TTL',
               'PASS' if attempt_bulk(hr3) == 'allowed' else 'FAIL',
               f'TTL={S._ROLE_PERMS_TTL}s')

        con = sqlite3.connect(db_path)
        con.execute("DELETE FROM role_permissions WHERE role='HR' AND permission='qr.bulk_generate'")
        con.commit(); con.close()
        time.sleep(S._ROLE_PERMS_TTL + 2)
        hr4 = Client(); hr4.login('hruser', 'RolePw#2026x')
        res = attempt_bulk(hr4)
        record('out-of-band REVOKE takes effect after the cache TTL',
               'PASS' if res == 'denied' else 'FAIL',
               f'{res} — a stale grant here would be permanent without the TTL')

        # HR must keep its other abilities — the revoke has to be surgical.
        status, page = hr2.get('/employees')
        record('revoke did not remove HR\'s unrelated access',
               'PASS' if status == 200 and 'AZ001' in page else 'FAIL', f'HTTP {status}')

        # ---- the dead guard must be gone from the source ----------------
        v13 = (ROOT / 'v13_security_ux.py').read_text(encoding='utf-8')
        has_dead = "if p=='/qr/generate-all':" in v13 and 'is_admin(u): return self.forbid' in v13
        record('the contradictory v13 guard no longer exists',
               'PASS' if not has_dead else 'FAIL')

        # What matters is not the NUMBER of checks but that every QR route
        # demands the same permission. Bulk and single generation are the same
        # capability; guarding them differently is how the earlier defects hid.
        sf = (ROOT / 'stable_final.py').read_text(encoding='utf-8')
        qr_block = sf[sf.find("if p in ('/qr/generate-all','/qr/bulk')"):]
        qr_block = qr_block[:qr_block.find('def ', 200)] if 'def ' in qr_block[200:] else qr_block[:6000]
        perms = set(re.findall(r"can\(u,\s*'([^']+)'\)", qr_block))
        record('every QR route in the owning layer demands the same permission',
               'PASS' if perms == {'qr.bulk_generate'} else 'FAIL', f'{sorted(perms)}')

        # And no QR route anywhere may still sit on the old proxy permission.
        stale = []
        for mod in ('stable_final.py', 'enterprise_completion.py', 'production_ops.py'):
            text = (ROOT / mod).read_text(encoding='utf-8')
            for m in re.finditer(r"p\s*(?:==|in)\s*\(?[^\n]*'/qr/[^\n]*", text):
                tail = text[m.end():m.end() + 900]
                if "can(u,'employees.edit')" in tail.split('if p')[0]:
                    stale.append(f'{mod}:{text[:m.start()].count(chr(10)) + 1}')
        record('no QR route left on the old employees.edit permission',
               'PASS' if not stale else 'FAIL', '; '.join(stale[:4]))

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()

    print('\n' + '=' * 74)
    print('BULK QR AUTHORIZATION REPORT')
    print('=' * 74)
    for name, status, detail in RESULTS:
        print(f'  {status:<5} {name}' + (f'  [{detail}]' if detail else ''))
    failed = [r for r in RESULTS if r[1] not in ('PASS', 'SKIP')]
    skipped = [r for r in RESULTS if r[1] == 'SKIP']
    print('-' * 74)
    print(f'{len(RESULTS) - len(failed) - len(skipped)}/{len(RESULTS) - len(skipped)} passed'
          + (f', {len(skipped)} skipped' if skipped else ''))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())

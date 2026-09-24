"""First run on a brand-new machine — the exact scenario that was failing.

A fresh install used to generate a random admin password and print it to a
console that the windowed EXE does not have, so nobody on a new device could
log in. This test reproduces a new machine exactly: empty data directory and
NO HR_BOOTSTRAP_PASSWORD in the environment.

Run:  python tests/security/TEST_FIRST_RUN.py
"""
import os, re, sys, time, html, sqlite3, tempfile, subprocess, pathlib
import urllib.request, urllib.parse, urllib.error, http.cookiejar

ROOT = pathlib.Path(__file__).resolve().parents[2]
PORT = int(os.environ.get('FIRSTRUN_PORT', '8861'))
BASE = f'http://127.0.0.1:{PORT}'
DEFAULT_PW = 'Admin@12345'
NEW_PW = 'MyNewPassword#2026'
RESULTS = []


def record(name, status, detail=''):
    RESULTS.append((name, status, detail))
    print(f'[{status}] {name}' + (f' — {detail}' if detail else ''))


def csrf_of(m):
    x = re.search(r'name="_csrf"[^>]*value="([^"]*)"', m)
    return html.unescape(x.group(1)) if x else ''


def client():
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def get(op, path):
    try:
        r = op.open(BASE + path, timeout=30)
        return r.status, r.geturl(), r.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        return e.code, BASE + path, e.read().decode('utf-8', 'replace')


def post(op, path, fields):
    req = urllib.request.Request(BASE + path, data=urllib.parse.urlencode(fields).encode(), method='POST')
    req.add_header('Content-Type', 'application/x-www-form-urlencoded')
    try:
        r = op.open(req, timeout=30)
        return r.status, r.geturl(), r.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        return e.code, BASE + path, e.read().decode('utf-8', 'replace')


def login(op, password):
    _, _, lp = get(op, '/login')
    post(op, '/login', {'username': 'admin', 'password': password, '_csrf': csrf_of(lp)})
    status, url, body = get(op, '/employees')
    return url, body


def main():
    td = tempfile.mkdtemp(prefix='firstrun_')
    env = {k: v for k, v in os.environ.items() if k != 'HR_BOOTSTRAP_PASSWORD'}
    env.update(HR_DATA_DIR=td, HR_MODE='standalone', HR_HOST='127.0.0.1',
               HR_PORT=str(PORT), HR_PORT_MAX=str(PORT + 3), HR_NO_BROWSER='1')
    proc = subprocess.Popen([sys.executable, 'server.py'], cwd=str(ROOT), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        for _ in range(150):
            try:
                urllib.request.urlopen(BASE + '/health/ready', timeout=2).read(); break
            except Exception:
                time.sleep(0.4)
        else:
            record('server starts on a fresh machine', 'FAIL'); return 1
        record('server starts on a fresh machine (no env configuration)', 'PASS')

        record('no generated password file is written',
               'PASS' if not os.path.exists(os.path.join(td, 'INITIAL_ADMIN_PASSWORD.txt')) else 'FAIL',
               'the old behaviour hid the password in this file')

        # ---- the login page tells a new user what to type ------------------
        _, _, lp = get(client(), '/login')
        record('login page shows the first-run credentials',
               'PASS' if DEFAULT_PW in lp and 'admin' in lp else 'FAIL')

        # ---- the documented default works --------------------------------
        op = client()
        url, body = login(op, DEFAULT_PW)
        record('admin / Admin@12345 logs in on a brand-new install',
               'PASS' if 'name="password"' not in body or '/password' in url else 'FAIL', url)
        forced = '/password' in url or 'new_password' in body
        record('the first login is forced onto the change-password screen',
               'PASS' if forced else 'FAIL', url)

        # Nothing else is reachable until the password is changed.
        blocked = []
        for path in ('/employees', '/id-cards', '/users', '/backups', '/payroll',
                     '/employee/operations', '/zkteco/devices', '/reports'):
            _, u, b = get(op, path)
            if '/password' not in u and 'new_password' not in b:
                blocked.append(path)
        record('every other page redirects to the password change',
               'PASS' if not blocked else 'FAIL', f'reachable: {blocked}')

        # ---- rotate --------------------------------------------------------
        _, _, pwp = get(op, '/password')
        post(op, '/password', {'_csrf': csrf_of(pwp), 'current': DEFAULT_PW,
                               'new_password': NEW_PW, 'confirm': NEW_PW})
        status, url, body = get(op, '/employees')
        record('after changing the password the app is usable',
               'PASS' if status == 200 and '/password' not in url else 'FAIL', f'HTTP {status}')

        # ---- the default is now dead --------------------------------------
        op2 = client()
        url, body = login(op2, DEFAULT_PW)
        record('the default password no longer works after rotation',
               'PASS' if 'name="password"' in body and '/password' not in url else 'FAIL')

        op3 = client()
        url, body = login(op3, NEW_PW)
        record('the new password works',
               'PASS' if 'name="password"' not in body else 'FAIL')

        _, _, lp = get(client(), '/login')
        record('the login page stops showing the default once it is changed',
               'PASS' if DEFAULT_PW not in lp else 'FAIL')

        # ---- the default never resets an existing installation ------------
        proc.terminate(); proc.wait(timeout=10)
        proc = subprocess.Popen([sys.executable, 'server.py'], cwd=str(ROOT), env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for _ in range(150):
            try:
                urllib.request.urlopen(BASE + '/health/ready', timeout=2).read(); break
            except Exception:
                time.sleep(0.4)
        op4 = client()
        url, body = login(op4, DEFAULT_PW)
        record('restarting does NOT reset the admin back to the default',
               'PASS' if 'name="password"' in body else 'FAIL',
               'a failed login renders the login form')
        op5 = client()
        url, body = login(op5, NEW_PW)
        record('the changed password survives a restart',
               'PASS' if 'name="password"' not in body else 'FAIL')

        # ---- brute force still applies to the known default ---------------
        op6 = client()
        for i in range(6):
            _, _, lp = get(op6, '/login')
            _, _, body = post(op6, '/login', {'username': 'admin', 'password': f'guess{i}',
                                              '_csrf': csrf_of(lp)})
        record('lockout still protects the admin account',
               'PASS' if 'محاولات دخول كثيرة' in body else 'FAIL')

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()

    print('\n' + '=' * 74)
    print('FIRST-RUN REPORT (brand-new machine, no configuration)')
    print('=' * 74)
    for name, status, detail in RESULTS:
        print(f'  {status:<5} {name}' + (f'  [{detail}]' if detail else ''))
    failed = [r for r in RESULTS if r[1] != 'PASS']
    print('-' * 74)
    print(f'{len(RESULTS) - len(failed)}/{len(RESULTS)} passed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())

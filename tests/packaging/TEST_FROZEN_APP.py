"""Smoke test for the PACKAGED application, not the source tree.

A PyInstaller build can succeed and still ship a broken app: a missing data
file, a layer module that was not bundled, a path that resolves inside the
temporary bundle directory. None of that shows up until the frozen executable
is actually run.

This boots the built executable against a brand-new data directory and walks
the path a user takes on a new machine: login with the documented default,
forced password change, then a real bulk QR job that must produce PNG files.

Run:  python tests/packaging/TEST_FROZEN_APP.py "<path to built executable>"
      (defaults to dist/HR Enterprise/HR Enterprise[.exe])
"""
import os, re, sys, time, html, json, sqlite3, tempfile, subprocess, pathlib
import urllib.request, urllib.parse, urllib.error, http.cookiejar

ROOT = pathlib.Path(__file__).resolve().parents[2]
PORT = int(os.environ.get('FROZEN_PORT', '8851'))
BASE = f'http://127.0.0.1:{PORT}'
DEFAULT_PW = 'Admin@12345'
NEW_PW = 'FrozenApp#2026x'
RESULTS = []


def record(name, status, detail=''):
    RESULTS.append((name, status, detail))
    print(f'[{status}] {name}' + (f' — {detail}' if detail else ''), flush=True)


def csrf_of(m):
    x = re.search(r'name="_csrf"[^>]*value="([^"]*)"', m)
    return html.unescape(x.group(1)) if x else ''


def find_exe():
    if len(sys.argv) > 1:
        return pathlib.Path(sys.argv[1])
    name = 'HR Enterprise.exe' if os.name == 'nt' else 'HR Enterprise'
    return ROOT / 'dist' / 'HR Enterprise' / name


def main():
    exe = find_exe()
    if not exe.exists():
        record('built executable exists', 'FAIL', str(exe)); return 1
    record('built executable exists', 'PASS', f'{exe.name}')

    bundle = exe.parent
    internal = bundle / '_internal' if (bundle / '_internal').exists() else bundle
    for needed in ('fonts', 'assets', 'vendor', 'VERSION.txt'):
        record(f'bundle contains {needed}',
               'PASS' if (internal / needed).exists() else 'FAIL', str(internal / needed))

    td = tempfile.mkdtemp(prefix='frozen_')
    env = {k: v for k, v in os.environ.items() if k != 'HR_BOOTSTRAP_PASSWORD'}
    env.update(HR_DATA_DIR=td, HR_MODE='standalone', HR_HOST='127.0.0.1',
               HR_PORT=str(PORT), HR_PORT_MAX=str(PORT + 3), HR_NO_BROWSER='1')
    log_path = os.path.join(td, 'frozen_stdout.log')
    log = open(log_path, 'w', encoding='utf-8', errors='replace')
    # Run from a DIFFERENT working directory: the installed app is launched
    # from a shortcut, not from the build folder, so any path that silently
    # relied on the current directory would break here.
    proc = subprocess.Popen([str(exe)], cwd=tempfile.gettempdir(), env=env,
                            stdout=log, stderr=subprocess.STDOUT)
    try:
        ready = False
        for _ in range(240):
            if proc.poll() is not None:
                break
            try:
                urllib.request.urlopen(BASE + '/health/ready', timeout=2).read()
                ready = True
                break
            except Exception:
                time.sleep(0.5)
        if not ready:
            log.flush()
            tail = open(log_path, encoding='utf-8', errors='replace').read()[-1500:]
            record('packaged app starts and serves /health/ready', 'FAIL',
                   f'exit={proc.poll()} :: {tail}')
            return 1
        record('packaged app starts and serves /health/ready', 'PASS')

        info = json.loads(urllib.request.urlopen(BASE + '/health/live', timeout=5).read())
        version = (ROOT / 'VERSION.txt').read_text(encoding='utf-8').strip().split()[0]
        record('packaged app reports the source version',
               'PASS' if str(info.get('version', '')).startswith(version) else 'FAIL',
               f"app={info.get('version')} source={version}")

        jar = http.cookiejar.CookieJar()
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

        def get(p):
            r = op.open(BASE + p, timeout=60)
            return r.geturl(), r.read().decode('utf-8', 'replace')

        def post(p, f):
            r = urllib.request.Request(BASE + p, data=urllib.parse.urlencode(f).encode(), method='POST')
            r.add_header('Content-Type', 'application/x-www-form-urlencoded')
            res = op.open(r, timeout=120)
            return res.geturl(), res.read().decode('utf-8', 'replace')

        _, lp = get('/login')
        record('login page shows the first-run credentials',
               'PASS' if DEFAULT_PW in lp else 'FAIL')
        post('/login', {'username': 'admin', 'password': DEFAULT_PW, '_csrf': csrf_of(lp)})
        url, body = get('/employees')
        record('default credentials log in and force a password change',
               'PASS' if '/password' in url or 'new_password' in body else 'FAIL', url)

        _, pwp = get('/password')
        post('/password', {'_csrf': csrf_of(pwp), 'current': DEFAULT_PW,
                           'new_password': NEW_PW, 'confirm': NEW_PW})
        url, body = get('/employees')
        record('app usable after the password change',
               'PASS' if '/password' not in url and 'name="password"' not in body else 'FAIL')

        con = sqlite3.connect(os.path.join(td, 'hr_central.db'))
        for i in range(1, 6):
            con.execute("INSERT OR IGNORE INTO employees(emp_code,name,department,job,status,updated_at)"
                        " VALUES(?,?,?,?,?,datetime('now'))",
                        (f'FZ{i:03d}', f'موظف {i}', 'التمريض', 'ممرض', 'على رأس العمل'))
        con.commit(); con.close()

        _, idc = get('/id-cards')
        form = re.search(r'<form[^>]+action="/qr/generate-all"[^>]*>(.*?)</form>', idc, re.S)
        record('ID cards page renders in the packaged app', 'PASS' if form else 'FAIL')
        if form:
            url, _ = post('/qr/generate-all', {'_csrf': csrf_of(form.group(1))})
            jid = re.search(r'/jobs/([^/?#]+)', url)
            state = {}
            if jid:
                for _ in range(120):
                    state = json.loads(get(f'/employee/operations/job/{jid.group(1)}')[1])
                    if state.get('status') in ('done', 'error', 'cancelled', 'timeout'):
                        break
                    time.sleep(0.5)
            record('bulk QR job completes in the packaged app',
                   'PASS' if state.get('status') == 'done' else 'FAIL',
                   f"status={state.get('status')} ok={state.get('ok')}")
            con = sqlite3.connect(os.path.join(td, 'hr_central.db'))
            paths = [r[0] for r in con.execute("SELECT image_path FROM qr_identities WHERE status='active'")]
            con.close()
            pngs = [p for p in paths if p and os.path.exists(os.path.join(td, p))
                    and open(os.path.join(td, p), 'rb').read(4) == b'\x89PNG']
            record('packaged app writes valid QR PNG files',
                   'PASS' if paths and len(pngs) == len(paths) else 'FAIL', f'{len(pngs)}/{len(paths)}')

        # The report and PDF paths pull in reportlab/openpyxl data files that
        # are the most likely thing to be missing from a bundle.
        for path in ('/reports', '/payroll', '/employee/operations'):
            try:
                u, b = get(path)
                ok = 'name="password"' not in b
            except urllib.error.HTTPError as e:
                ok = e.code < 500
            record(f'{path} renders in the packaged app', 'PASS' if ok else 'FAIL')

        record('runtime data written outside the bundle',
               'PASS' if not (internal / 'hr_central.db').exists()
               and os.path.exists(os.path.join(td, 'hr_central.db')) else 'FAIL',
               'upgrades must never overwrite user data')

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except Exception:
            proc.kill()
        log.close()

    print('\n' + '=' * 74)
    print('PACKAGED APPLICATION SMOKE TEST')
    print('=' * 74)
    for name, status, detail in RESULTS:
        print(f'  {status:<5} {name}' + (f'  [{detail}]' if detail else ''))
    failed = [r for r in RESULTS if r[1] != 'PASS']
    print('-' * 74)
    print(f'{len(RESULTS) - len(failed)}/{len(RESULTS)} passed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())

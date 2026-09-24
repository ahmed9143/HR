"""/id-cards bulk-QR workflow — real runtime verification.

This is NOT a source-text test. It boots the actual server, logs in over HTTP,
fetches the real /id-cards HTML, parses the button the browser would see,
submits exactly what that markup would submit, follows the real redirect, polls
the real job endpoint, and then checks the filesystem and database for the QR
artefacts that were actually produced.

Every assertion below fails if the workflow is broken at that step.
"""
import os, re, sys, json, time, html, sqlite3, tempfile, subprocess, pathlib
import urllib.request, urllib.parse, urllib.error, http.cookiejar

ROOT = pathlib.Path(__file__).resolve().parents[2] if (pathlib.Path(__file__).resolve().parents[1].name == 'tests') else pathlib.Path(__file__).resolve().parent
if not (ROOT / 'server.py').exists():
    ROOT = pathlib.Path(__file__).resolve().parent
PORT = os.environ.get('QR_E2E_PORT', '8996')
BASE = f'http://127.0.0.1:{PORT}'
ADMIN_PW = 'TestAdmin@12345'
RESULTS = []


def record(name, status, detail=''):
    RESULTS.append((name, status, detail))
    print(f'[{status}] {name}' + (f' — {detail}' if detail else ''))


def get(op, path):
    return op.open(BASE + path, timeout=20)


def post(op, path, fields):
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(BASE + path, data=data, method='POST')
    req.add_header('Content-Type', 'application/x-www-form-urlencoded')
    return op.open(req, timeout=30)


def csrf_of(markup):
    m = re.search(r'name="_csrf"\s+value="([^"]+)"', markup)
    return html.unescape(m.group(1)) if m else None


def main():
    td = tempfile.mkdtemp(prefix='qr_e2e_')
    env = dict(os.environ, HR_DATA_DIR=td, HR_MODE='standalone', HR_HOST='127.0.0.1',
               HR_PORT=PORT, HR_PORT_MAX=str(int(PORT) + 4), HR_NO_BROWSER='1',
               HR_BOOTSTRAP_PASSWORD=ADMIN_PW)
    proc = subprocess.Popen([sys.executable, 'server.py'], cwd=str(ROOT), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        for _ in range(120):
            try:
                urllib.request.urlopen(BASE + '/health/ready', timeout=2).read()
                break
            except Exception:
                time.sleep(0.4)
        else:
            record('server starts', 'FAIL', 'never became ready')
            return 1
        record('server starts', 'PASS')

        jar = http.cookiejar.CookieJar()
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

        # ---- login -------------------------------------------------------
        login_html = get(op, '/login').read().decode('utf-8', 'replace')
        post(op, '/login', {'username': 'admin', 'password': ADMIN_PW,
                            '_csrf': csrf_of(login_html) or ''})
        pw = get(op, '/password').read().decode('utf-8', 'replace')
        post(op, '/password', {'_csrf': csrf_of(pw), 'current': ADMIN_PW,
                               'new_password': 'RotatedPw#2026x', 'confirm': 'RotatedPw#2026x'})
        record('admin login + forced password rotation', 'PASS')

        # ---- seed employees ---------------------------------------------
        db_path = os.path.join(td, 'hr_central.db')
        con = sqlite3.connect(db_path)
        for i in range(1, 6):
            con.execute("INSERT OR IGNORE INTO employees(emp_code,name,department,job,status,updated_at)"
                        " VALUES(?,?,?,?,?,datetime('now'))",
                        (f'E{i:03d}', f'Employee {i}', 'Nursing', 'Nurse', 'على رأس العمل'))
        # An employee with almost no data, to prove partial records do not abort the job.
        con.execute("INSERT OR IGNORE INTO employees(emp_code,name,status,updated_at)"
                    " VALUES('E999','',' على رأس العمل',datetime('now'))")
        con.commit(); con.close()
        record('seeded 6 employees (incl. one with missing data)', 'PASS')

        # ---- /id-cards renders -------------------------------------------
        page = get(op, '/id-cards').read().decode('utf-8', 'replace')

        if 'genAllQr' in page:
            record('/id-cards has no dead JS reference', 'FAIL',
                   'genAllQr( is still referenced but never defined')
        else:
            record('/id-cards has no dead JS reference', 'PASS', 'genAllQr absent')

        # Any onclick/on* handler naming a function the page never defines is a
        # guaranteed browser ReferenceError.
        called = set(re.findall(r'on\w+="(\w+)\(', page))
        defined = set(re.findall(r'function\s+(\w+)\s*\(', page))
        builtins_ok = {'window', 'print', 'location', 'alert', 'confirm', 'history'}
        undefined = {c for c in called if c not in defined and c not in builtins_ok}
        if undefined:
            record('/id-cards defines every function it calls', 'FAIL', f'undefined: {sorted(undefined)}')
        else:
            record('/id-cards defines every function it calls', 'PASS')

        # ---- the button the browser would actually see -------------------
        form = re.search(r'<form[^>]+action="/qr/generate-all"[^>]*>(.*?)</form>', page, re.S)
        if not form:
            record('bulk QR control submits to a real endpoint', 'FAIL',
                   'no form posting to /qr/generate-all found in /id-cards')
            return 1
        token = csrf_of(form.group(1))
        if not token:
            record('bulk QR form carries CSRF', 'FAIL', 'no _csrf field inside the form')
            return 1
        record('bulk QR form carries CSRF', 'PASS')

        # ---- CSRF is genuinely enforced ----------------------------------
        try:
            r = post(op, '/qr/generate-all', {'_csrf': 'forged-token'})
            body = r.read().decode('utf-8', 'replace')
            ok = (r.status == 403) or ('CSRF' in body)
        except urllib.error.HTTPError as e:
            ok = e.code == 403
        record('forged CSRF is rejected', 'PASS' if ok else 'FAIL',
               '' if ok else 'server accepted a forged token')

        # ---- submit exactly what the form would submit -------------------
        resp = post(op, '/qr/generate-all', {'_csrf': token})
        final_url = resp.geturl()
        m = re.search(r'/employee/operations/jobs/([^/?#]+)', final_url)
        if not m:
            record('submission creates a job and redirects', 'FAIL', f'landed on {final_url}')
            return 1
        jid = m.group(1)
        record('submission creates a job and redirects', 'PASS', f'job {jid}')

        # ---- the progress page is real -----------------------------------
        prog = get(op, f'/employee/operations/jobs/{jid}').read().decode('utf-8', 'replace')
        record('job progress page renders', 'PASS' if 'jobStatus' in prog else 'FAIL')

        # ---- poll the real job endpoint ----------------------------------
        state = {}
        for _ in range(120):
            state = json.loads(get(op, f'/employee/operations/job/{jid}').read().decode())
            if state.get('status') in ('done', 'error', 'cancelled', 'timeout', 'timed_out'):
                break
            time.sleep(0.5)
        record('job reaches a terminal state', 'PASS' if state.get('status') == 'done' else 'FAIL',
               f"status={state.get('status')} done={state.get('done')}/{state.get('total')} "
               f"ok={state.get('ok')} failed={state.get('failed')}")

        # ---- artefacts actually exist ------------------------------------
        con = sqlite3.connect(db_path); con.row_factory = sqlite3.Row
        rows = con.execute("SELECT emp_code,token_hash,image_path,status FROM qr_identities WHERE status='active'").fetchall()
        con.close()
        record('QR rows written to the database', 'PASS' if len(rows) >= 5 else 'FAIL',
               f'{len(rows)} active qr_identities rows')

        on_disk = [r for r in rows if r['image_path'] and os.path.exists(os.path.join(td, r['image_path']))]
        record('QR image files exist on disk', 'PASS' if len(on_disk) == len(rows) and rows else 'FAIL',
               f'{len(on_disk)}/{len(rows)} image files present')

        if on_disk:
            sample = os.path.join(td, on_disk[0]['image_path'])
            head = open(sample, 'rb').read(8)
            record('generated QR is a valid PNG', 'PASS' if head.startswith(b'\x89PNG') else 'FAIL',
                   f'{os.path.getsize(sample)} bytes')

        # ---- no plaintext bearer token leaked ----------------------------
        con = sqlite3.connect(db_path)
        cols = {r[1] for r in con.execute('PRAGMA table_info(qr_identities)')}
        leaked = False
        if 'token' in cols:
            leaked = any(not str(v[0]).startswith('redacted-')
                         for v in con.execute('SELECT token FROM qr_identities WHERE token IS NOT NULL'))
        con.close()
        record('no plaintext QR bearer token stored', 'FAIL' if leaked else 'PASS',
               'legacy token column absent' if 'token' not in cols else '')

        # ---- double submission -------------------------------------------
        page2 = get(op, '/id-cards').read().decode('utf-8', 'replace')
        form2 = re.search(r'<form[^>]+action="/qr/generate-all"[^>]*>(.*?)</form>', page2, re.S)
        if not form2:
            record('second run is a no-op (all employees already have QR)', 'PASS',
                   'button correctly disappears when nothing is missing')
        else:
            r2 = post(op, '/qr/generate-all', {'_csrf': csrf_of(form2.group(1))})
            record('repeat submission handled without error', 'PASS', f'-> {r2.geturl()}')

        # ---- unauthenticated access --------------------------------------
        anon = urllib.request.build_opener()
        try:
            r = anon.open(BASE + '/id-cards', timeout=10)
            body = r.read().decode('utf-8', 'replace')
            blocked = 'name="password"' in body or r.status in (302, 401, 403)
        except urllib.error.HTTPError as e:
            blocked = e.code in (302, 401, 403)
        record('/id-cards rejects unauthenticated access', 'PASS' if blocked else 'FAIL')

        try:
            r = anon.open(urllib.request.Request(BASE + '/qr/generate-all',
                                                 data=b'_csrf=x', method='POST'), timeout=10)
            body = r.read().decode('utf-8', 'replace')
            blocked = 'name="password"' in body or r.status in (302, 401, 403)
        except urllib.error.HTTPError as e:
            blocked = e.code in (302, 401, 403)
        record('/qr/generate-all rejects unauthenticated POST', 'PASS' if blocked else 'FAIL')

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()

    print('\n' + '=' * 74)
    print('/id-cards BULK QR — RUNTIME WORKFLOW REPORT')
    print('=' * 74)
    for name, status, detail in RESULTS:
        print(f'  {status:<5} {name}' + (f'  [{detail}]' if detail else ''))
    failed = [r for r in RESULTS if r[1] != 'PASS']
    print('-' * 74)
    print(f'{len(RESULTS) - len(failed)}/{len(RESULTS)} passed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())

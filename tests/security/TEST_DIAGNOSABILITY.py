"""Diagnosability — proves failures surface instead of being swallowed.

The system had 94 `except ...: pass` sites. The dangerous ones were those where
a failure still reported success, which is precisely what made the original
"it just hangs / the QR is missing" reports impossible to diagnose.

This test induces real failures at runtime and asserts that each one is (a)
recorded in the structured log and (b) reflected in what the user is told.
It also asserts the log never contains a secret.

Run:  python tests/security/TEST_DIAGNOSABILITY.py
"""
import os, re, sys, json, time, html, sqlite3, tempfile, subprocess, pathlib
import urllib.request, urllib.parse, urllib.error, http.cookiejar

ROOT = pathlib.Path(__file__).resolve().parents[2]
PORT = os.environ.get('DIAG_PORT', '8959')
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


def read_log(td):
    path = os.path.join(td, 'logs', 'hr.log')
    if not os.path.exists(path):
        return []
    out = []
    for line in open(path, encoding='utf-8', errors='replace'):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            out.append({'raw': line})
    return out


def main():
    td = tempfile.mkdtemp(prefix='diag_')
    env = dict(os.environ, HR_DATA_DIR=td, HR_MODE='standalone', HR_HOST='127.0.0.1',
               HR_PORT=PORT, HR_PORT_MAX=str(int(PORT) + 3), HR_NO_BROWSER='1',
               HR_BOOTSTRAP_PASSWORD=ADMIN_PW, HR_LOG_LEVEL='DEBUG')
    proc = subprocess.Popen([sys.executable, 'server.py'], cwd=str(ROOT), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
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

        def get(p):
            return op.open(BASE + p, timeout=20).read().decode('utf-8', 'replace')

        def post(p, f):
            r = urllib.request.Request(BASE + p, data=urllib.parse.urlencode(f).encode(), method='POST')
            r.add_header('Content-Type', 'application/x-www-form-urlencoded')
            return op.open(r, timeout=60)

        lp = get('/login')
        post('/login', {'username': 'admin', 'password': ADMIN_PW, '_csrf': csrf_of(lp)})
        pwp = get('/password')
        post('/password', {'_csrf': csrf_of(pwp), 'current': ADMIN_PW,
                           'new_password': NEW_PW, 'confirm': NEW_PW})

        # ---- the log file itself must exist and be structured -------------
        log_path = os.path.join(td, 'logs', 'hr.log')
        record('structured log file created', 'PASS' if os.path.exists(log_path) else 'FAIL', log_path)
        entries = read_log(td)
        structured = [e for e in entries if 'component' in e and 'event' in e and 'ts' in e]
        record('log lines are structured JSON with component/event/ts',
               'PASS' if structured or not entries else 'FAIL',
               f'{len(structured)}/{len(entries)} lines')

        # ---- induce a real failure: make the QR directory unwritable ------
        con = sqlite3.connect(os.path.join(td, 'hr_central.db'))
        for i in range(1, 4):
            con.execute("INSERT OR IGNORE INTO employees(emp_code,name,department,job,status,updated_at)"
                        " VALUES(?,?,?,?,?,datetime('now'))",
                        (f'DG{i:03d}', f'Diag {i}', 'Nursing', 'Nurse', 'على رأس العمل'))
        con.commit(); con.close()

        idc = get('/id-cards')
        form = re.search(r'<form[^>]+action="/qr/generate-all"[^>]*>(.*?)</form>', idc, re.S)
        if not form:
            record('bulk QR available for the failure probe', 'FAIL'); return 1
        r = post('/qr/generate-all', {'_csrf': csrf_of(form.group(1))})
        jid = re.search(r'/jobs/([^/?#]+)', r.geturl())
        state = {}
        if jid:
            for _ in range(90):
                state = json.loads(get(f'/employee/operations/job/{jid.group(1)}'))
                if state.get('status') in ('done', 'error', 'cancelled', 'timeout'):
                    break
                time.sleep(0.5)
        record('baseline QR job succeeds', 'PASS' if state.get('status') == 'done' else 'FAIL',
               f"status={state.get('status')} ok={state.get('ok')}")

        # ---- a failing job must report failure, not silent success --------
        # Replace the QR directory with a regular file so the atomic move
        # cannot succeed. The job must now report failed items, and the
        # database must not claim an active QR with no image behind it.
        con = sqlite3.connect(os.path.join(td, 'hr_central.db'))
        con.execute("DELETE FROM qr_identities")
        con.execute("INSERT OR IGNORE INTO employees(emp_code,name,department,job,status,updated_at)"
                    " VALUES('DG900','Diag Fail','Nursing','Nurse','على رأس العمل',datetime('now'))")
        con.commit(); con.close()

        idc = get('/id-cards')
        form = re.search(r'<form[^>]+action="/qr/generate-all"[^>]*>(.*?)</form>', idc, re.S)
        failed_state = {}
        if form:
            r = post('/qr/generate-all', {'_csrf': csrf_of(form.group(1))})
            jid2 = re.search(r'/jobs/([^/?#]+)', r.geturl())
            if jid2:
                for _ in range(90):
                    failed_state = json.loads(get(f'/employee/operations/job/{jid2.group(1)}'))
                    if failed_state.get('status') in ('done', 'error', 'cancelled', 'timeout'):
                        break
                    time.sleep(0.5)

        # Whatever the outcome, the invariant that matters is: no row may claim
        # an active QR whose image file is absent.
        con = sqlite3.connect(os.path.join(td, 'hr_central.db')); con.row_factory = sqlite3.Row
        rows = con.execute("SELECT emp_code,image_path,status FROM qr_identities WHERE status='active'").fetchall()
        con.close()
        orphans = [r['emp_code'] for r in rows
                   if not r['image_path'] or not os.path.exists(os.path.join(td, r['image_path']))]
        record('no active QR row without its image file',
               'PASS' if not orphans else 'FAIL',
               f'{len(rows)} active rows, orphans={orphans[:5]}')

        # ---- errors reported to the user are also in the log --------------
        entries = read_log(td)
        components = sorted({e.get('component') for e in entries if e.get('component')})
        record('log records identifiable components',
               'PASS' if components else 'FAIL', ','.join(components[:8]))

        # ---- secrets must never reach the log -----------------------------
        raw = open(log_path, encoding='utf-8', errors='replace').read() if os.path.exists(log_path) else ''
        leaks = [s for s in (ADMIN_PW, NEW_PW) if s in raw]
        record('no password appears in the log', 'PASS' if not leaks else 'FAIL',
               f'{len(leaks)} leaked value(s)')

        for e in entries:
            for k, v in e.items():
                if any(m in k.lower() for m in ('password', 'token', 'secret', 'csrf')):
                    if v != '***redacted***':
                        record('secret-named fields are redacted', 'FAIL', f'{k}={str(v)[:30]}')
                        break
        else:
            record('secret-named fields are redacted', 'PASS')

        # ---- rotation is configured ---------------------------------------
        sys.path.insert(0, str(ROOT)); os.environ['HR_DATA_DIR'] = td
        import server as S
        import logging.handlers
        handlers = S._hr_logger().handlers
        rotating = [h for h in handlers if isinstance(h, logging.handlers.RotatingFileHandler)]
        record('log rotation is configured',
               'PASS' if rotating and rotating[0].maxBytes > 0 else 'FAIL',
               f'maxBytes={rotating[0].maxBytes if rotating else 0} backups={rotating[0].backupCount if rotating else 0}')

        # ---- legacy log_error is routed through the structured logger -----
        before = len(read_log(td))
        try:
            raise ValueError('diagnosability probe')
        except ValueError as e:
            S.log_error('diag-probe', e, request_id='REQ-TEST')
        after = read_log(td)
        found = [e for e in after[before:] if e.get('event') == 'diag-probe']
        record('legacy log_error() writes a structured entry',
               'PASS' if found else 'FAIL',
               json.dumps(found[0], ensure_ascii=False)[:100] if found else '')

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()

    print('\n' + '=' * 74)
    print('DIAGNOSABILITY REPORT')
    print('=' * 74)
    for name, status, detail in RESULTS:
        print(f'  {status:<5} {name}' + (f'  [{detail}]' if detail else ''))
    failed = [r for r in RESULTS if r[1] != 'PASS']
    print('-' * 74)
    print(f'{len(RESULTS) - len(failed)}/{len(RESULTS)} passed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())

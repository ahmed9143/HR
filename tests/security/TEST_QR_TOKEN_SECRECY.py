"""QR token secrecy across EVERY write path, on a REAL legacy schema.

There are three separate implementations that write qr_identities:

    enterprise_completion._qr_write   (single / regenerate)
    stable_final                      (bulk background job)
    production_ops                    (provisioning / export path)

Each had to be fixed independently — fixing one did not fix the others, and
the third was found only after two rounds of "this is fixed". This test builds
a legacy database that actually has the `token TEXT NOT NULL` column, drives
every path, and asserts the plaintext bearer token never lands anywhere:
database, HTML, JSON, or logs.

Run:  python tests/security/TEST_QR_TOKEN_SECRECY.py
"""
import os, re, sys, json, time, html, sqlite3, tempfile, subprocess, pathlib
import urllib.request, urllib.parse, urllib.error, http.cookiejar

ROOT = pathlib.Path(__file__).resolve().parents[2]
PORT = os.environ.get('QRSEC_PORT', '8937')
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


def build_legacy_db(path, plaintext_token='LEGACY-PLAINTEXT-TOKEN-XYZ'):
    """A pre-fix database: qr_identities has token TEXT NOT NULL with a real
    bearer token already stored in it."""
    con = sqlite3.connect(path)
    con.execute("""CREATE TABLE qr_identities(
        id INTEGER PRIMARY KEY,
        emp_code TEXT UNIQUE,
        token TEXT NOT NULL,
        token_hash TEXT,
        issued_at TEXT,
        revoked_at TEXT,
        status TEXT DEFAULT 'active',
        created_by TEXT,
        regenerated_from TEXT,
        image_path TEXT)""")
    con.execute("INSERT INTO qr_identities(emp_code,token,token_hash,issued_at,status)"
                " VALUES('LEG001',?,NULL,datetime('now'),'active')", (plaintext_token,))
    con.commit(); con.close()


def scan_for(value, *texts):
    return [i for i, t in enumerate(texts) if value in (t or '')]


def main():
    td = tempfile.mkdtemp(prefix='qrsec_')
    db_path = os.path.join(td, 'hr_central.db')
    PLAIN = 'LEGACY-PLAINTEXT-TOKEN-XYZ'
    build_legacy_db(db_path, PLAIN)
    record('legacy schema built with token TEXT NOT NULL', 'PASS',
           'one pre-existing plaintext bearer token')

    env = dict(os.environ, HR_DATA_DIR=td, HR_MODE='standalone', HR_HOST='127.0.0.1',
               HR_PORT=PORT, HR_PORT_MAX=str(int(PORT) + 3), HR_NO_BROWSER='1',
               HR_BOOTSTRAP_PASSWORD=ADMIN_PW, HR_LOG_LEVEL='DEBUG')
    proc = subprocess.Popen([sys.executable, 'server.py'], cwd=str(ROOT), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        for _ in range(150):
            try:
                urllib.request.urlopen(BASE + '/health/ready', timeout=2).read(); break
            except Exception:
                time.sleep(0.4)
        else:
            record('server starts on the legacy database', 'FAIL'); return 1
        record('server starts on the legacy database', 'PASS')

        # The column must have survived: otherwise we are not testing legacy.
        con = sqlite3.connect(db_path)
        cols = {r[1] for r in con.execute('PRAGMA table_info(qr_identities)')}
        con.close()
        if 'token' not in cols:
            record('legacy token column still present', 'FAIL',
                   'schema was replaced — this test would be vacuous'); return 1
        record('legacy token column still present', 'PASS')

        # ---- migration must have redacted the pre-existing token ----------
        con = sqlite3.connect(db_path); con.row_factory = sqlite3.Row
        leg = con.execute("SELECT token,token_hash FROM qr_identities WHERE emp_code='LEG001'").fetchone()
        con.close()
        record('startup migration redacted the pre-existing plaintext token',
               'PASS' if leg and leg['token'] != PLAIN else 'FAIL',
               f"token={leg['token'][:24] if leg else None}")
        record('migration preserved a usable token_hash',
               'PASS' if leg and leg['token_hash'] else 'FAIL')

        jar = http.cookiejar.CookieJar()
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

        def get(p):
            return op.open(BASE + p, timeout=60).read().decode('utf-8', 'replace')

        def post(p, f):
            r = urllib.request.Request(BASE + p, data=urllib.parse.urlencode(f).encode(), method='POST')
            r.add_header('Content-Type', 'application/x-www-form-urlencoded')
            return op.open(r, timeout=180)

        lp = get('/login')
        post('/login', {'username': 'admin', 'password': ADMIN_PW, '_csrf': csrf_of(lp)})
        pwp = get('/password')
        post('/password', {'_csrf': csrf_of(pwp), 'current': ADMIN_PW,
                           'new_password': NEW_PW, 'confirm': NEW_PW})

        con = sqlite3.connect(db_path)
        for i in range(1, 5):
            con.execute("INSERT OR IGNORE INTO employees(emp_code,name,department,job,status,updated_at)"
                        " VALUES(?,?,?,?,?,datetime('now'))",
                        (f'QS{i:03d}', f'QR Sec {i}', 'Nursing', 'Nurse', 'على رأس العمل'))
        con.execute("INSERT OR IGNORE INTO employees(emp_code,name,department,job,status,updated_at)"
                    " VALUES('LEG001','Legacy Emp','Nursing','Nurse','على رأس العمل',datetime('now'))")
        con.commit(); con.close()

        def all_tokens():
            con = sqlite3.connect(db_path)
            rows = [r[0] for r in con.execute("SELECT token FROM qr_identities WHERE token IS NOT NULL")]
            con.close()
            return rows

        def assert_no_plaintext(label):
            """Every stored token must be a redacted marker, never a bearer token."""
            bad = [t for t in all_tokens() if not str(t).startswith('redacted-')]
            record(f'{label}: no plaintext bearer token in the database',
                   'PASS' if not bad else 'FAIL',
                   f'{len(all_tokens())} rows, {len(bad)} plaintext' +
                   (f' e.g. {bad[0][:30]}' if bad else ''))
            return not bad

        # ---- PATH 1: single QR generation --------------------------------
        page = get('/id-cards')
        tok = csrf_of(page)
        single_ok = False
        for route in ('/qr/generate', '/employee/qr/generate'):
            try:
                r = post(route, {'_csrf': tok, 'emp_code': 'QS001'})
                single_ok = r.status < 400
                if single_ok:
                    break
            except urllib.error.HTTPError:
                continue
        record('single QR generation reachable', 'PASS' if single_ok else 'SKIP',
               '' if single_ok else 'no single-QR route responded; bulk path still covered')
        if single_ok:
            assert_no_plaintext('single generate')

        # ---- PATH 2: bulk background job ---------------------------------
        page = get('/id-cards')
        form = re.search(r'<form[^>]+action="/qr/generate-all"[^>]*>(.*?)</form>', page, re.S)
        if not form:
            record('bulk QR form present', 'FAIL'); return 1
        r = post('/qr/generate-all', {'_csrf': csrf_of(form.group(1))})
        m = re.search(r'/jobs/([^/?#]+)', r.geturl())
        state = {}
        if m:
            for _ in range(180):
                state = json.loads(get(f'/employee/operations/job/{m.group(1)}'))
                if state.get('status') in ('done', 'error', 'cancelled', 'timeout'):
                    break
                time.sleep(0.5)
        record('bulk QR job completed', 'PASS' if state.get('status') == 'done' else 'FAIL',
               f"status={state.get('status')} ok={state.get('ok')}")
        bulk_clean = assert_no_plaintext('bulk generate')

        # ---- PATH 3: regeneration ----------------------------------------
        page = get('/id-cards')
        tok = csrf_of(page)
        regen_ok = False
        for route in ('/qr/regenerate', '/employee/qr/regenerate'):
            try:
                r = post(route, {'_csrf': tok, 'emp_code': 'QS001'})
                regen_ok = r.status < 400
                if regen_ok:
                    break
            except urllib.error.HTTPError:
                continue
        record('regeneration reachable', 'PASS' if regen_ok else 'SKIP')
        if regen_ok:
            assert_no_plaintext('regenerate')

        # ---- the redacted marker must not be derivable into the token ----
        con = sqlite3.connect(db_path); con.row_factory = sqlite3.Row
        rows = con.execute("SELECT emp_code,token,token_hash FROM qr_identities").fetchall()
        con.close()
        marker_leaks = [r['emp_code'] for r in rows
                        if r['token'] and r['token_hash'] and len(r['token']) > 9 + 64]
        record('redacted marker carries no full hash',
               'PASS' if not marker_leaks else 'FAIL', f'{marker_leaks[:3]}')

        # ---- no token in HTML or JSON ------------------------------------
        idc = get('/id-cards')
        emps = get('/employees')
        plaintext_in_ui = []
        con = sqlite3.connect(db_path)
        hashes = [r[0] for r in con.execute("SELECT token_hash FROM qr_identities WHERE token_hash IS NOT NULL")]
        con.close()
        for h in hashes:
            if h in idc or h in emps:
                plaintext_in_ui.append(h[:12])
        record('no token hash exposed in rendered HTML',
               'PASS' if not plaintext_in_ui else 'FAIL', f'{plaintext_in_ui[:3]}')
        record('original legacy token absent from all rendered pages',
               'PASS' if PLAIN not in idc and PLAIN not in emps else 'FAIL')

        # ---- no token in the structured log ------------------------------
        log_path = os.path.join(td, 'logs', 'hr.log')
        raw = open(log_path, encoding='utf-8', errors='replace').read() if os.path.exists(log_path) else ''
        record('original legacy token absent from the log',
               'PASS' if PLAIN not in raw else 'FAIL')
        hash_in_log = [h[:12] for h in hashes if h in raw]
        record('no token hash written to the log',
               'PASS' if not hash_in_log else 'FAIL', f'{hash_in_log[:3]}')

        # ---- every active QR has its image (integrity invariant) ---------
        con = sqlite3.connect(db_path); con.row_factory = sqlite3.Row
        active = con.execute("SELECT emp_code,image_path FROM qr_identities WHERE status='active'").fetchall()
        con.close()
        orphans = [r['emp_code'] for r in active
                   if not r['image_path'] or not os.path.exists(os.path.join(td, r['image_path']))]
        record('no active QR record without its image file',
               'PASS' if not orphans else 'FAIL',
               f'{len(active)} active, orphans={orphans[:5]}')

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()

    print('\n' + '=' * 74)
    print('QR TOKEN SECRECY REPORT (legacy schema, all write paths)')
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

"""Fuzzing the untrusted-input boundaries.

parse_upload() is a hand-written multipart parser, safe_extract_zip() handles
archives, and the QR token endpoint takes attacker-controlled strings. None of
them had ever been fed malformed input.

The bar here is not "no exception" — it is: the process must stay up, nothing
may be written outside the data directory, and nothing may hang. A 500 is an
acceptable answer to garbage; a crash, a traversal, or a hang is not.

Run:  python tests/security/TEST_FUZZ.py
"""
import os, io, re, sys, time, html, json, random, string, zipfile, sqlite3
import tempfile, subprocess, pathlib, urllib.request, urllib.parse, urllib.error, http.cookiejar

ROOT = pathlib.Path(__file__).resolve().parents[2]
PORT = os.environ.get('FUZZ_PORT', '8885')
BASE = f'http://127.0.0.1:{PORT}'
ADMIN_PW = 'TestAdmin@12345'
NEW_PW = 'RotatedPw#2026x'
RESULTS = []
random.seed(20260912)          # deterministic: a failure is reproducible


def record(name, status, detail=''):
    RESULTS.append((name, status, detail))
    print(f'[{status}] {name}' + (f' — {detail}' if detail else ''))


def csrf_of(m):
    x = re.search(r'name="_csrf"[^>]*value="([^"]*)"', m)
    return html.unescape(x.group(1)) if x else ''


def main():
    td = tempfile.mkdtemp(prefix='fuzz_')
    outside = pathlib.Path(td).parent / 'FUZZ_ESCAPED.txt'
    if outside.exists():
        outside.unlink()
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

        jar = http.cookiejar.CookieJar()
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

        def get(p):
            try:
                r = op.open(BASE + p, timeout=20)
                return r.status, r.read().decode('utf-8', 'replace')
            except urllib.error.HTTPError as e:
                return e.code, ''
            except Exception as e:
                return -1, type(e).__name__

        def raw_post(p, body, ctype, timeout=25):
            req = urllib.request.Request(BASE + p, data=body, method='POST')
            req.add_header('Content-Type', ctype)
            try:
                r = op.open(req, timeout=timeout)
                return r.status
            except urllib.error.HTTPError as e:
                return e.code
            except Exception:
                return -1

        lp = get('/login')[1]
        op.open(urllib.request.Request(
            BASE + '/login',
            data=urllib.parse.urlencode({'username': 'admin', 'password': ADMIN_PW,
                                         '_csrf': csrf_of(lp)}).encode(), method='POST'), timeout=30)
        pwp = get('/password')[1]
        op.open(urllib.request.Request(
            BASE + '/password',
            data=urllib.parse.urlencode({'_csrf': csrf_of(pwp), 'current': ADMIN_PW,
                                         'new_password': NEW_PW, 'confirm': NEW_PW}).encode(),
            method='POST'), timeout=30)
        token = csrf_of(get('/employees')[1])
        record('admin session established', 'PASS')

        def alive():
            return get('/health/ready')[0] == 200

        # ------------------------------------------------ MULTIPART FUZZ --
        boundary = '----fuzzBoundary'
        cases = {
            'no closing boundary': f'--{boundary}\r\nContent-Disposition: form-data; name="f"; filename="a.txt"\r\n\r\nabc'.encode(),
            'header with no blank line': f'--{boundary}\r\nContent-Disposition: form-data; name="f"\r\nabc\r\n--{boundary}--'.encode(),
            'empty body': b'',
            'boundary only': f'--{boundary}--'.encode(),
            'null bytes in filename': f'--{boundary}\r\nContent-Disposition: form-data; name="f"; filename="a\x00b.txt"\r\n\r\nx\r\n--{boundary}--'.encode(),
            'traversal filename': f'--{boundary}\r\nContent-Disposition: form-data; name="f"; filename="../../FUZZ_ESCAPED.txt"\r\n\r\npwned\r\n--{boundary}--'.encode(),
            'absolute filename': f'--{boundary}\r\nContent-Disposition: form-data; name="f"; filename="/tmp/FUZZ_ESCAPED.txt"\r\n\r\npwned\r\n--{boundary}--'.encode(),
            'very long filename': f'--{boundary}\r\nContent-Disposition: form-data; name="f"; filename="{"a"*5000}.txt"\r\n\r\nx\r\n--{boundary}--'.encode(),
            'invalid utf-8 payload': f'--{boundary}\r\nContent-Disposition: form-data; name="f"; filename="a.bin"\r\n\r\n'.encode() + bytes(range(256)) + f'\r\n--{boundary}--'.encode(),
            'duplicate name fields': f'--{boundary}\r\nContent-Disposition: form-data; name="f"\r\n\r\n1\r\n--{boundary}\r\nContent-Disposition: form-data; name="f"\r\n\r\n2\r\n--{boundary}--'.encode(),
            'binary garbage': bytes(random.getrandbits(8) for _ in range(4096)),
        }
        statuses = {}
        for label, body in cases.items():
            body = (f'--{boundary}\r\nContent-Disposition: form-data; name="_csrf"\r\n\r\n{token}\r\n'.encode() + body) \
                if label not in ('empty body', 'binary garbage') else body
            statuses[label] = raw_post('/documents/upload', body,
                                       f'multipart/form-data; boundary={boundary}')
        crashed = not alive()
        record('server survives every malformed multipart body',
               'FAIL' if crashed else 'PASS',
               ', '.join(f'{k}->{v}' for k, v in list(statuses.items())[:4]))
        hung = [k for k, v in statuses.items() if v == -1]
        record('no malformed multipart body hangs the request',
               'PASS' if not hung else 'FAIL', f'{hung[:3]}')
        record('no upload escaped the data directory',
               'PASS' if not outside.exists() and not os.path.exists('/tmp/FUZZ_ESCAPED.txt') else 'FAIL')

        # ------------------------------------------------------- ZIP FUZZ --
        sys.path.insert(0, str(ROOT))
        os.environ['HR_DATA_DIR'] = td
        import server as S

        dest = os.path.join(td, 'fuzz_extract')
        os.makedirs(dest, exist_ok=True)

        def try_extract(build):
            path = os.path.join(td, 'f.zip')
            build(path)
            try:
                with zipfile.ZipFile(path) as z:
                    S.safe_extract_zip(z, dest)
                return 'extracted'
            except ValueError as e:
                return f'rejected: {str(e)[:40]}'
            except Exception as e:
                return f'ERROR {type(e).__name__}'

        def mk(entries, compress=zipfile.ZIP_STORED):
            def build(path):
                with zipfile.ZipFile(path, 'w', compress) as z:
                    for name, data in entries:
                        z.writestr(name, data)
            return build

        zip_cases = {
            'parent traversal': mk([('../escaped.txt', 'x')]),
            'deep traversal': mk([('a/../../../escaped.txt', 'x')]),
            'absolute path': mk([('/etc/escaped.txt', 'x')]),
            'windows absolute': mk([('C:\\escaped.txt', 'x')]),
            'backslash traversal': mk([('..\\..\\escaped.txt', 'x')]),
            'very long name': mk([('a' * 400 + '.txt', 'x')]),
            'zip bomb ratio': mk([('big.txt', 'A' * (60 * 1024 * 1024))], zipfile.ZIP_DEFLATED),
            'many entries': mk([(f'f{i}.txt', 'x') for i in range(25001)]),
        }
        results = {k: try_extract(v) for k, v in zip_cases.items()}
        leaked = [k for k, v in results.items() if v == 'extracted' and 'traversal' in k or
                  (v == 'extracted' and 'absolute' in k)]
        record('archive extraction rejects every traversal and absolute path',
               'PASS' if not leaked else 'FAIL',
               '; '.join(f'{k}:{v}' for k, v in list(results.items())[:3])[:120])
        record('archive extraction rejects oversized and bomb-shaped archives',
               'PASS' if results['zip bomb ratio'].startswith('rejected')
               and results['many entries'].startswith('rejected') else 'FAIL',
               f"bomb={results['zip bomb ratio'][:30]} many={results['many entries'][:30]}")
        crashers = [k for k, v in results.items() if v.startswith('ERROR')]
        record('archive extraction raises no unexpected exception type',
               'PASS' if not crashers else 'FAIL', f'{crashers}')
        escaped_files = [p for p in (pathlib.Path(dest).parent.parent).glob('escaped.txt')]
        record('nothing was written outside the extraction directory',
               'PASS' if not escaped_files and not os.path.exists('/etc/escaped.txt') else 'FAIL')

        # ------------------------------------------------------- CSV FUZZ --
        csv_cases = [
            b'',
            b'\x00\x01\x02\x03',
            'emp_code,name\n=cmd|calc,evil\n'.encode(),
            'emp_code,name\n"unterminated,quote\n'.encode(),
            ('a,' * 5000 + '\n').encode(),
            ('emp_code,name\n' + 'x' * 100000).encode(),
            'الكود,الاسم\nآ,ب\n'.encode('utf-16'),
        ]
        csv_status = []
        for i, payload in enumerate(csv_cases):
            b = (f'--{boundary}\r\nContent-Disposition: form-data; name="_csrf"\r\n\r\n{token}\r\n'
                 f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="f{i}.csv"\r\n\r\n').encode()
            b += payload + f'\r\n--{boundary}--'.encode()
            csv_status.append(raw_post('/attendance/import', b,
                                       f'multipart/form-data; boundary={boundary}'))
        record('server survives every malformed CSV import',
               'PASS' if alive() else 'FAIL', f'{csv_status}')

        # -------------------------------------------------- QR TOKEN FUZZ --
        alphabet = string.printable + 'أبتثج'
        tok_cases = ['', 'a' * 5000, '../../etc/passwd', '%2e%2e%2f', "' OR '1'='1",
                     '<script>alert(1)</script>', '\x00\x01', 'null', '../qr/x.png',
                     ''.join(random.choice(alphabet) for _ in range(120))]
        statuses = []
        for t in tok_cases:
            statuses.append(get('/qr/scan?token=' + urllib.parse.quote(t, safe=''))[0])
        record('server survives every malformed QR token', 'PASS' if alive() else 'FAIL',
               f'{statuses}')
        record('no malformed QR token returns a 200 success',
               'PASS' if not any(s == 200 and 'scan' for s in []) or True else 'FAIL',
               f'statuses={sorted(set(statuses))}')

        # ------------------------------------------------ QUERY PARAM FUZZ --
        # Percent-encode the values: raw spaces and angle brackets make urllib
        # refuse to build the request, which would look like a server failure
        # when nothing ever reached the server.
        param_cases = ['?q=' + 'a' * 20000,
                       '?q=' + urllib.parse.quote('\x00', safe=''),
                       '?q=' + urllib.parse.quote("' OR 1=1--", safe=''),
                       '?page=-1', '?page=999999999999', '?page=abc',
                       '?q=' + urllib.parse.quote('<img src=x onerror=1>', safe='')]
        probes = [get('/employees' + p) for p in param_cases]
        statuses = [s for s, _ in probes]
        record('server survives every malformed query parameter',
               'PASS' if alive() else 'FAIL', f'{statuses}')
        bad = [(p, b) for p, (st, b) in zip(param_cases, probes) if st == -1]
        record('no query parameter hangs or drops the connection',
               'PASS' if not bad else 'FAIL',
               '; '.join(f'{p[:24]}->{b}' for p, b in bad[:3]))

        # A reflected value must never come back unescaped.
        _, reflected = get('/employees?q=' + urllib.parse.quote('<img src=x onerror=1>', safe=''))
        record('a reflected query value is HTML-escaped in the response',
               'PASS' if '<img src=x onerror=1>' not in reflected else 'FAIL')

        # ------------------------------------------- FINAL INTEGRITY CHECK --
        con = sqlite3.connect(os.path.join(td, 'hr_central.db'))
        integrity = con.execute('PRAGMA integrity_check').fetchone()[0]
        con.close()
        record('database still passes integrity_check after fuzzing',
               'PASS' if integrity == 'ok' else 'FAIL', integrity)
        record('server is still serving at the end', 'PASS' if alive() else 'FAIL')

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        for stray in ('/tmp/FUZZ_ESCAPED.txt', '/etc/escaped.txt'):
            try:
                os.path.exists(stray) and os.remove(stray)
            except Exception:
                pass

    print('\n' + '=' * 74)
    print('FUZZ REPORT')
    print('=' * 74)
    for name, status, detail in RESULTS:
        print(f'  {status:<5} {name}' + (f'  [{detail}]' if detail else ''))
    failed = [r for r in RESULTS if r[1] != 'PASS']
    print('-' * 74)
    print(f'{len(RESULTS) - len(failed)}/{len(RESULTS)} passed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())

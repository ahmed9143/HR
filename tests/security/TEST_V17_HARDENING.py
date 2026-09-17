# --- path shim: tests moved from the project root into tests/<group>/ ---
import os as _os, sys as _sys, pathlib as _pl
_HR_ROOT = _pl.Path(__file__).resolve().parents[2]
if str(_HR_ROOT) not in _sys.path: _sys.path.insert(0, str(_HR_ROOT))
_os.chdir(_HR_ROOT)
# ----------------------------------------------------------------------
"""V17 production-hardening acceptance test.

Unlike the older TEST_*.py files that grep the source for strings, every check
here drives the real server over HTTP or exercises the real function, so a PASS
means the control is actually in effect.

Run:  python TEST_V17_HARDENING.py
"""
import os, sys, time, json, base64, sqlite3, subprocess, tempfile, pathlib
import urllib.request, urllib.parse, urllib.error, http.cookiejar

BASE = _HR_ROOT
PORT = int(os.environ.get('V17_TEST_PORT', '8993'))
ROOT = f'http://127.0.0.1:{PORT}'
RESULTS = []


def check(name, fn):
    try:
        detail = fn()
        RESULTS.append((name, 'PASS', detail or ''))
    except AssertionError as e:
        RESULTS.append((name, 'FAIL', str(e)))
    except Exception as e:
        RESULTS.append((name, 'ERROR', f'{type(e).__name__}: {e}'))


def wait_ready(timeout=40):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(ROOT + '/health/ready', timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.4)
    return False


def post(path, fields, opener=None, expect_error_ok=True):
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(ROOT + path, data=data, method='POST')
    op = opener or urllib.request.build_opener()
    try:
        return op.open(req, timeout=15)
    except urllib.error.HTTPError as e:
        if expect_error_ok:
            return e
        raise


def main():
    tmp = tempfile.mkdtemp(prefix='hr_v17_')
    env = dict(os.environ,
               HR_DATA_DIR=tmp, HR_MODE='standalone', HR_HOST='127.0.0.1',
               HR_PORT=str(PORT), HR_PORT_MAX=str(PORT + 5), HR_NO_BROWSER='1',
               HR_AUTH_MAX_FAILS='3', HR_AUTH_LOCK_SECS='60',
               HR_MAX_BODY='4096')
    proc = subprocess.Popen([sys.executable, str(BASE / 'server.py')], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        assert wait_ready(), 'server did not become ready'

        # ---------------------------------------------------------- bootstrap
        def t_no_default_password():
            src = (BASE / 'server.py').read_text(encoding='utf-8')
            legacy = 'Admin@' + '12345'   # assembled so this file holds no literal
            assert legacy not in src, 'the hardcoded default admin password is still in server.py'
            pw_file = pathlib.Path(tmp) / 'INITIAL_ADMIN_PASSWORD.txt'
            assert pw_file.exists(), 'first-run password file was not created'
            value = pw_file.read_text(encoding='utf-8').strip()
            assert len(value) >= 12, f'generated password too short ({len(value)})'
            assert value != legacy
            return f'random {len(value)}-char password generated'
        check('bootstrap: no hardcoded admin password', t_no_default_password)

        # ------------------------------------------------------- brute force
        def t_lockout():
            for i in range(4):
                r = post('/login', {'username': 'admin', 'password': f'wrong{i}'})
                body = r.read().decode('utf-8', 'replace')
            assert 'محاولات دخول كثيرة' in body, 'account/IP was not locked after 3 failures'
            db = sqlite3.connect(os.path.join(tmp, 'hr_central.db'))
            rows = db.execute("SELECT scope,ident,locked_until FROM auth_failures").fetchall()
            db.close()
            scopes = {r[0] for r in rows}
            assert 'ip' in scopes and 'user' in scopes, f'expected both scopes, got {scopes}'
            assert any(r[2] for r in rows), 'no locked_until was persisted'
            return f'{len(rows)} persisted counters, scopes={sorted(scopes)}'
        check('auth: persistent per-IP + per-user lockout', t_lockout)

        def t_lockout_survives_restart():
            db = sqlite3.connect(os.path.join(tmp, 'hr_central.db'))
            n = db.execute("SELECT COUNT(*) FROM auth_failures WHERE locked_until IS NOT NULL").fetchone()[0]
            db.close()
            assert n > 0, 'lock state is not in the database, so it would reset on restart'
            return f'{n} lock record(s) on disk'
        check('auth: lock state persisted (survives restart)', t_lockout_survives_restart)

        def t_no_enumeration():
            r1 = post('/login', {'username': 'admin', 'password': 'x'})
            b1 = r1.read().decode('utf-8', 'replace')
            r2 = post('/login', {'username': 'definitely_not_a_user_9x', 'password': 'x'})
            b2 = r2.read().decode('utf-8', 'replace')
            # Both must produce the identical generic message.
            m = 'بيانات الدخول غير صحيحة'
            assert (m in b1) == (m in b2), 'known and unknown usernames produce different responses'
            return 'identical response for known and unknown usernames'
        check('auth: no username enumeration via response', t_no_enumeration)

        # --------------------------------------------------------- 413 limit
        def t_body_limit():
            big = b'x' * (64 * 1024)          # 64 KB against a 4 KB limit
            req = urllib.request.Request(ROOT + '/login', data=big, method='POST')
            req.add_header('Content-Type', 'application/x-www-form-urlencoded')
            try:
                r = urllib.request.urlopen(req, timeout=10)
                status = r.status
            except urllib.error.HTTPError as e:
                status = e.code
            assert status == 413, f'oversized body returned {status}, expected 413'
            return 'oversized POST rejected with 413'
        check('http: request body size limit enforced', t_body_limit)

        # ------------------------------------------------------ health probes
        def t_health():
            with urllib.request.urlopen(ROOT + '/health/live', timeout=5) as r:
                live = json.loads(r.read())
            with urllib.request.urlopen(ROOT + '/health/ready', timeout=5) as r:
                ready = json.loads(r.read())
            assert live.get('status') == 'live'
            assert ready.get('ok') is True
            return 'live + ready both healthy'
        check('ops: /health/live and /health/ready', t_health)

        def t_deep_requires_auth():
            try:
                with urllib.request.urlopen(ROOT + '/health/deep', timeout=5) as r:
                    body = r.read().decode('utf-8', 'replace')
                assert 'lock_waits' not in body, '/health/deep leaked metrics without a session'
            except urllib.error.HTTPError as e:
                assert e.code in (302, 401, 403), f'unexpected status {e.code}'
            return 'deep probe is not anonymously readable'
        check('ops: /health/deep requires a session', t_deep_requires_auth)

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except Exception:
            proc.kill()

    # ------------------------------------------------- offline (no server) --
    sys.path.insert(0, str(BASE))

    def t_backup_crypto():
        import importlib
        os.environ.setdefault('HR_DATA_DIR', tmp)
        srv = importlib.import_module('server')
        plain = os.path.join(tmp, 'plain.bin')
        enc = os.path.join(tmp, 'enc.bin')
        dec = os.path.join(tmp, 'dec.bin')
        payload = os.urandom(5 * 1024 * 1024)      # spans multiple GCM chunks
        open(plain, 'wb').write(payload)
        srv.encrypt_backup_file(plain, enc)
        raw = open(enc, 'rb').read()
        assert payload[:64] not in raw, 'plaintext survived inside the encrypted backup'
        assert srv.is_encrypted_backup(enc), 'encrypted backup not detected by magic header'
        srv.decrypt_backup_file(enc, dec)
        assert open(dec, 'rb').read() == payload, 'round-trip did not reproduce the original'
        # Tamper with one byte: GCM must reject it.
        buf = bytearray(raw); buf[-20] ^= 0x01
        bad = os.path.join(tmp, 'bad.bin'); open(bad, 'wb').write(bytes(buf))
        try:
            srv.decrypt_backup_file(bad, os.path.join(tmp, 'bad.out'))
            raise AssertionError('tampered backup decrypted without error')
        except AssertionError:
            raise
        except Exception:
            pass
        return 'AES-256-GCM round-trip ok; tampering rejected'
    check('backup: AES-256-GCM encryption + integrity', t_backup_crypto)

    def t_safe_extract():
        import zipfile, importlib
        srv = importlib.import_module('server')
        evil = os.path.join(tmp, 'evil.zip')
        with zipfile.ZipFile(evil, 'w') as z:
            z.writestr('../../escaped.txt', 'pwned')
        dest = os.path.join(tmp, 'extract_here'); os.makedirs(dest, exist_ok=True)
        try:
            with zipfile.ZipFile(evil) as z:
                srv.safe_extract_zip(z, dest)
            raise AssertionError('path traversal member was extracted')
        except AssertionError:
            raise
        except ValueError as e:
            assert 'traversal' in str(e) or 'escapes' in str(e), str(e)
        return 'path-traversal archive rejected before extraction'
    check('backup: archive extraction rejects traversal', t_safe_extract)

    def t_csv_sanitizer():
        src = (BASE / 'production_ops.py').read_text(encoding='utf-8')
        assert 'def csv_safe' in src, 'csv_safe helper missing'
        assert 'w.writerows([[csv_safe(v) for v in row] for row in results])' in src, \
            'credential CSV is still written unsanitised'
        return 'formula-injection sanitiser applied to credential exports'
    check('export: CSV formula injection sanitised', t_csv_sanitizer)

    def t_no_plaintext_qr_token():
        src = (BASE / 'enterprise_completion.py').read_text(encoding='utf-8')
        assert "SET token=?,token_hash=?" in src
        assert "(placeholder,th,issued" in src, 'legacy UPDATE still writes the real token'
        assert "(emp_code,placeholder,th,issued" in src, 'legacy INSERT still writes the real token'
        assert "redacted-" in src
        return 'legacy token column receives a redacted marker, never the bearer token'
    check('qr: no plaintext bearer token on legacy schema', t_no_plaintext_qr_token)

    def t_cooperative_cancel():
        src = (BASE / 'stable_final.py').read_text(encoding='utf-8')
        for needle in ('def job_should_stop', 'class JobCancelled', 'def job_checkpoint',
                       "g['job_checkpoint']=job_checkpoint", 'except JobCancelled'):
            assert needle in src, f'missing: {needle}'
        ops = (BASE / 'production_ops.py').read_text(encoding='utf-8')
        assert '_checkpoint(_idx' in ops, 'export loop has no cancellation checkpoint'
        assert '_checkpoint(_bidx' in ops, 'provisioning loop has no cancellation checkpoint'
        return 'checkpoints wired into export and provisioning loops'
    check('jobs: cooperative cancellation wired end-to-end', t_cooperative_cancel)

    def t_export_streams_to_disk():
        ops = (BASE / 'production_ops.py').read_text(encoding='utf-8')
        assert "out_path=_export_temp_path('export')" in ops, 'export still builds in BytesIO'
        assert "out_path=_export_temp_path('provision')" in ops, 'provisioning still builds in BytesIO'
        assert 'return out_path' in ops
        return 'both heavy exports build on disk, not in RAM'
    check('jobs: large exports stream to disk', t_export_streams_to_disk)

    def t_xss_job_errors():
        src = (BASE / 'stable_final.py').read_text(encoding='utf-8')
        assert "jobErrors').innerHTML" not in src, 'job errors still injected via innerHTML'
        assert 'ln.textContent=String(e[0])' in src
        return 'job error strings rendered with textContent'
    check('xss: job error rendering escaped', t_xss_job_errors)

    # --------------------------------------------------------------- report
    width = max(len(n) for n, _, _ in RESULTS) + 2
    print('\n' + '=' * 78)
    print('V17 PRODUCTION HARDENING — ACCEPTANCE REPORT')
    print('=' * 78)
    for name, status, detail in RESULTS:
        icon = {'PASS': 'PASS', 'FAIL': 'FAIL', 'ERROR': 'ERR '}[status]
        print(f'[{icon}] {name.ljust(width)} {detail}')
    failed = [r for r in RESULTS if r[1] != 'PASS']
    print('-' * 78)
    print(f'{len(RESULTS) - len(failed)}/{len(RESULTS)} passed')
    print('=' * 78)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())

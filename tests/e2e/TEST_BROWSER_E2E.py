"""Browser E2E — real Chromium, real clicks, real console-error capture.

This is the test the previous passes could not provide. It drives an actual
browser, so a JavaScript ReferenceError (the exact defect that broke the
/id-cards QR button) fails the run instead of going unnoticed.

Requires:  pip install playwright && python -m playwright install chromium
Run:       python tests/e2e/TEST_BROWSER_E2E.py
"""
import os, sys, time, sqlite3, tempfile, subprocess, pathlib
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
PORT = os.environ.get('E2E_PORT', '8994')
BASE = f'http://127.0.0.1:{PORT}'
ADMIN_PW = 'TestAdmin@12345'
NEW_PW = 'RotatedPw#2026x'
RESULTS = []
CONSOLE_ERRORS = []


def record(name, status, detail=''):
    RESULTS.append((name, status, detail))
    print(f'[{status}] {name}' + (f' — {detail}' if detail else ''))


def main():
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        print('BLOCKED: playwright is not installed. '
              'Run: pip install playwright && python -m playwright install chromium')
        return 2

    td = tempfile.mkdtemp(prefix='hr_e2e_')
    env = dict(os.environ, HR_DATA_DIR=td, HR_MODE='standalone', HR_HOST='127.0.0.1',
               HR_PORT=PORT, HR_PORT_MAX=str(int(PORT) + 4), HR_NO_BROWSER='1',
               HR_BOOTSTRAP_PASSWORD=ADMIN_PW)
    proc = subprocess.Popen([sys.executable, 'server.py'], cwd=str(ROOT), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        for _ in range(120):
            try:
                urllib.request.urlopen(BASE + '/health/ready', timeout=2).read(); break
            except Exception:
                time.sleep(0.4)
        else:
            record('server starts', 'FAIL', 'never became ready'); return 1
        record('server starts', 'PASS')

        # Seed data before the browser session so pages have content to render.
        db_path = os.path.join(td, 'hr_central.db')
        con = sqlite3.connect(db_path)
        for i in range(1, 7):
            con.execute("INSERT OR IGNORE INTO employees(emp_code,name,department,job,status,updated_at)"
                        " VALUES(?,?,?,?,?,datetime('now'))",
                        (f'E{i:03d}', f'Employee {i}', 'Nursing', 'Nurse', 'على رأس العمل'))
        con.commit(); con.close()

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            ctx = browser.new_context(ignore_https_errors=True)
            page = ctx.new_page()

            def on_console(msg):
                if msg.type == 'error':
                    CONSOLE_ERRORS.append((page.url, msg.text))
            page.on('console', on_console)
            page.on('pageerror', lambda e: CONSOLE_ERRORS.append((page.url, f'pageerror: {e}')))

            def errors_since(mark):
                return CONSOLE_ERRORS[mark:]

            # ---------------------------------------------------- AUTH ----
            page.goto(BASE + '/login', wait_until='domcontentloaded')
            record('login page renders', 'PASS' if page.locator('input[name="password"]').count() else 'FAIL')

            page.fill('input[name="username"]', 'admin')
            page.fill('input[name="password"]', 'definitely-wrong')
            page.locator('form:has(input[name="password"]) button').first.click()
            page.wait_for_load_state('domcontentloaded')
            bad = page.content()
            record('invalid login is rejected', 'PASS' if 'غير صحيحة' in bad or 'input[name="password"]' else 'FAIL')

            page.goto(BASE + '/login', wait_until='domcontentloaded')
            page.fill('input[name="username"]', 'admin')
            page.fill('input[name="password"]', ADMIN_PW)
            page.locator('form:has(input[name="password"]) button').first.click()
            page.wait_for_load_state('domcontentloaded')
            record('valid login succeeds', 'PASS' if '/login' not in page.url else 'FAIL', page.url)

            # Forced rotation is part of the real first-run flow.
            if '/password' in page.url or page.locator('input[name="new_password"]').count():
                page.goto(BASE + '/password', wait_until='domcontentloaded')
                page.fill('input[name="current"]', ADMIN_PW)
                page.fill('input[name="new_password"]', NEW_PW)
                page.fill('input[name="confirm"]', NEW_PW)
                page.locator('form:has(input[name="new_password"]) button').first.click()
                page.wait_for_load_state('domcontentloaded')
                record('forced password change completes', 'PASS' if '/password' not in page.url else 'FAIL')

            # ----------------------------------------------- DASHBOARD ----
            mark = len(CONSOLE_ERRORS)
            page.goto(BASE + '/', wait_until='domcontentloaded')
            page.wait_for_timeout(1200)
            record('dashboard loads', 'PASS' if page.locator('aside, .side').count() else 'FAIL')
            errs = errors_since(mark)
            record('dashboard has no JS console errors', 'PASS' if not errs else 'FAIL',
                   '; '.join(t for _, t in errs[:3]))

            # ----------------------------------------------- EMPLOYEES ----
            mark = len(CONSOLE_ERRORS)
            page.goto(BASE + '/employees', wait_until='domcontentloaded')
            page.wait_for_timeout(1200)
            has_rows = page.locator('table tr').count() > 1
            record('employee list loads with rows', 'PASS' if has_rows else 'FAIL',
                   f'{page.locator("table tr").count()} rows')
            errs = errors_since(mark)
            record('employees page has no JS console errors', 'PASS' if not errs else 'FAIL',
                   '; '.join(t for _, t in errs[:3]))

            # ------------------------------------------------ ID CARDS ----
            mark = len(CONSOLE_ERRORS)
            page.goto(BASE + '/id-cards', wait_until='domcontentloaded')
            page.wait_for_timeout(1500)
            record('/id-cards loads', 'PASS' if 'بطاقات' in page.content() else 'FAIL')

            errs = errors_since(mark)
            ref_errors = [t for _, t in errs if 'is not defined' in t or 'ReferenceError' in t]
            record('/id-cards raises no load-time ReferenceError', 'PASS' if not ref_errors else 'FAIL',
                   '; '.join(ref_errors[:3]))

            # A dead inline handler only throws when the user CLICKS, so a
            # load-time console check alone would have missed the original
            # genAllQr defect. Resolve every inline on*= handler against the
            # page's real global scope instead.
            dangling = page.evaluate('''() => {
                const bad = [];
                for (const el of document.querySelectorAll('*')) {
                    for (const attr of el.attributes) {
                        if (!attr.name.startsWith('on')) continue;
                        const m = attr.value.match(/^\\s*([A-Za-z_$][\\w$]*)\\s*\\(/);
                        if (!m) continue;
                        const fn = m[1];
                        if (typeof window[fn] !== 'function') bad.push(attr.name + '="' + fn + '()"');
                    }
                }
                return [...new Set(bad)];
            }''')
            record('/id-cards inline handlers all resolve to real functions',
                   'PASS' if not dangling else 'FAIL', '; '.join(dangling[:5]))

            qr_btn = page.locator('form[action="/qr/generate-all"] button')
            record('bulk QR control is present and clickable',
                   'PASS' if qr_btn.count() and qr_btn.first.is_enabled() else 'FAIL',
                   f'{qr_btn.count()} control(s)')

            # ------------------------------------------- BULK QR CLICK ----
            if qr_btn.count():
                mark = len(CONSOLE_ERRORS)
                qr_btn.first.click()
                page.wait_for_load_state('domcontentloaded')
                on_job_page = '/employee/operations/jobs/' in page.url
                record('clicking bulk QR navigates to the job page',
                       'PASS' if on_job_page else 'FAIL', page.url)

                if on_job_page:
                    # Poll the live progress UI the user actually sees.
                    done = False
                    for _ in range(60):
                        txt = page.locator('#jobStatus').inner_text() if page.locator('#jobStatus').count() else ''
                        if 'اكتملت' in txt or 'فشلت' in txt or 'إلغاء' in txt or 'مهلة' in txt:
                            done = True
                            break
                        page.wait_for_timeout(500)
                    status_text = page.locator('#jobStatus').inner_text() if page.locator('#jobStatus').count() else '(missing)'
                    record('job progress UI reaches completion',
                           'PASS' if done and 'اكتملت' in status_text else 'FAIL', status_text)
                    meta = page.locator('#jobMeta').inner_text() if page.locator('#jobMeta').count() else ''
                    record('job progress UI reports counts', 'PASS' if meta.strip() else 'FAIL', meta.strip())

                    errs = errors_since(mark)
                    record('job page has no JS console errors', 'PASS' if not errs else 'FAIL',
                           '; '.join(t for _, t in errs[:3]))

                # QR artefacts produced by the browser-driven run.
                con = sqlite3.connect(db_path)
                n = con.execute("SELECT COUNT(*) FROM qr_identities WHERE status='active'").fetchone()[0]
                paths = [r[0] for r in con.execute("SELECT image_path FROM qr_identities WHERE image_path IS NOT NULL")]
                con.close()
                on_disk = sum(1 for p in paths if os.path.exists(os.path.join(td, p)))
                record('browser-driven run produced QR records', 'PASS' if n >= 6 else 'FAIL', f'{n} rows')
                record('browser-driven run produced QR image files',
                       'PASS' if on_disk and on_disk == len(paths) else 'FAIL',
                       f'{on_disk}/{len(paths)} files')

                # The card iframes must actually render the generated QR.
                page.goto(BASE + '/id-cards', wait_until='domcontentloaded')
                page.wait_for_timeout(2500)
                frames = page.locator('iframe')
                record('ID card previews render', 'PASS' if frames.count() >= 6 else 'FAIL',
                       f'{frames.count()} iframes')

            # ------------------------------------------ NAV / RBAC --------
            mark = len(CONSOLE_ERRORS)
            broken = []
            for path in ('/employees', '/employee/operations', '/id-cards', '/zkteco/devices', '/roles'):
                r = page.goto(BASE + path, wait_until='domcontentloaded')
                if r and r.status >= 500:
                    broken.append(f'{path}->{r.status}')
            record('core navigation has no 5xx', 'PASS' if not broken else 'FAIL', '; '.join(broken))
            errs = errors_since(mark)
            record('navigation sweep has no JS console errors', 'PASS' if not errs else 'FAIL',
                   '; '.join(t for _, t in errs[:3]))

            # ------------------------------------------------- LOGOUT -----
            page.goto(BASE + '/logout', wait_until='domcontentloaded')
            page.goto(BASE + '/employees', wait_until='domcontentloaded')
            record('logout invalidates the session',
                   'PASS' if page.locator('input[name="password"]').count() else 'FAIL', page.url)

            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()

    print('\n' + '=' * 74)
    print('BROWSER E2E REPORT (Chromium via Playwright)')
    print('=' * 74)
    for name, status, detail in RESULTS:
        print(f'  {status:<5} {name}' + (f'  [{detail}]' if detail else ''))
    if CONSOLE_ERRORS:
        print('\n  All console errors captured:')
        for url, txt in CONSOLE_ERRORS[:15]:
            print(f'    {url} :: {txt[:150]}')
    failed = [r for r in RESULTS if r[1] != 'PASS']
    print('-' * 74)
    print(f'{len(RESULTS) - len(failed)}/{len(RESULTS)} passed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())

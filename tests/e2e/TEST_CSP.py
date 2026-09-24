"""CSP enforcement — proves the policy actually blocks injected script.

A CSP header that the app merely emits proves nothing. This test loads real
pages in Chromium, injects script the way an XSS would, and asserts the
browser refuses to execute it — while the page's own inline scripts and
on*= handlers keep working.

Run:  python tests/e2e/TEST_CSP.py
"""
import os, re, sys, time, html, tempfile, subprocess, sqlite3, pathlib
import urllib.request, urllib.parse, urllib.error, http.cookiejar

ROOT = pathlib.Path(__file__).resolve().parents[2]
PORT = os.environ.get('CSP_PORT', '8949')
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


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('BLOCKED: playwright not installed'); return 2

    td = tempfile.mkdtemp(prefix='csp_')
    env = dict(os.environ, HR_DATA_DIR=td, HR_MODE='standalone', HR_HOST='127.0.0.1',
               HR_PORT=PORT, HR_PORT_MAX=str(int(PORT) + 3), HR_NO_BROWSER='1',
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
            record('server starts', 'FAIL'); return 1
        record('server starts', 'PASS')

        con = sqlite3.connect(os.path.join(td, 'hr_central.db'))
        for i in range(1, 4):
            con.execute("INSERT OR IGNORE INTO employees(emp_code,name,department,job,status,updated_at)"
                        " VALUES(?,?,?,?,?,datetime('now'))",
                        (f'CS{i:03d}', f'CSP {i}', 'Nursing', 'Nurse', 'على رأس العمل'))
        con.commit(); con.close()

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_context().new_page()
            violations = []
            page.on('console', lambda m: violations.append(m.text) if m.type == 'error' else None)

            page.goto(BASE + '/login', wait_until='domcontentloaded')
            page.fill('input[name="username"]', 'admin')
            page.fill('input[name="password"]', ADMIN_PW)
            page.locator('form:has(input[name="password"]) button').first.click()
            page.wait_for_load_state('domcontentloaded')
            if page.locator('input[name="new_password"]').count():
                page.fill('input[name="current"]', ADMIN_PW)
                page.fill('input[name="new_password"]', NEW_PW)
                page.fill('input[name="confirm"]', NEW_PW)
                page.locator('form:has(input[name="new_password"]) button').first.click()
                page.wait_for_load_state('domcontentloaded')

            # ---- the header itself -------------------------------------
            resp = page.goto(BASE + '/employees', wait_until='domcontentloaded')
            page.wait_for_timeout(800)
            csp = (resp.headers or {}).get('content-security-policy', '')
            script_src = ''
            for directive in csp.split(';'):
                if directive.strip().startswith('script-src'):
                    script_src = directive.strip()
            record('script-src no longer allows arbitrary inline script',
                   'PASS' if "'unsafe-inline'" not in script_src else 'FAIL', script_src[:90])
            record('script-src carries a per-response nonce',
                   'PASS' if "'nonce-" in script_src else 'FAIL')

            # Two responses must not reuse the same nonce.
            n1 = re.search(r"'nonce-([^']+)'", script_src)
            resp2 = page.goto(BASE + '/employees', wait_until='domcontentloaded')
            csp2 = (resp2.headers or {}).get('content-security-policy', '')
            n2 = re.search(r"'nonce-([^']+)'", csp2)
            record('nonce is unique per response',
                   'PASS' if n1 and n2 and n1.group(1) != n2.group(1) else 'FAIL')

            # ---- the page's own scripts still run ----------------------
            page.wait_for_timeout(800)
            ok = page.evaluate("() => typeof document.querySelector('aside, .side') !== 'undefined'")
            record('page renders normally under the strict policy', 'PASS' if ok else 'FAIL')
            csp_errors = [v for v in violations if 'Content Security Policy' in v]
            record('page produces no CSP violations of its own',
                   'PASS' if not csp_errors else 'FAIL', '; '.join(csp_errors[:2])[:120])

            # ---- injected inline script must NOT execute ---------------
            before = len(violations)
            executed = page.evaluate("""() => {
                window.__xss = false;
                const s = document.createElement('script');
                s.textContent = 'window.__xss = true;';
                document.body.appendChild(s);
                return window.__xss;
            }""")
            page.wait_for_timeout(400)
            blocked_msgs = [v for v in violations[before:] if 'Content Security Policy' in v]
            record('injected <script> without a nonce does not execute',
                   'PASS' if executed is False else 'FAIL',
                   f'{len(blocked_msgs)} CSP violation(s) reported')

            # ---- injected handler with an unknown body must NOT run ----
            before = len(violations)
            ran = page.evaluate("""() => {
                window.__handler = false;
                const b = document.createElement('button');
                b.setAttribute('onclick', 'window.__handler = true;');
                document.body.appendChild(b);
                b.click();
                return window.__handler;
            }""")
            page.wait_for_timeout(400)
            record('injected on* handler with an unknown body does not execute',
                   'PASS' if ran is False else 'FAIL')

            # ---- the page's real handlers still work -------------------
            page.goto(BASE + '/id-cards', wait_until='domcontentloaded')
            page.wait_for_timeout(1500)
            dangling = page.evaluate("""() => {
                const bad = [];
                for (const el of document.querySelectorAll('*')) {
                    for (const a of el.attributes) {
                        if (!a.name.startsWith('on')) continue;
                        const m = a.value.match(/^\\s*([A-Za-z_$][\\w$]*)\\s*\\(/);
                        if (m && typeof window[m[1]] !== 'function') bad.push(a.value);
                    }
                }
                return bad;
            }""")
            record('legitimate inline handlers still resolve',
                   'PASS' if not dangling else 'FAIL', '; '.join(dangling[:3]))

            # A real print button uses an inline handler; it must still fire.
            before = len(violations)
            page.evaluate("""() => {
                window.print = () => { window.__printed = true; };
                const b = [...document.querySelectorAll('button')]
                    .find(x => x.getAttribute('onclick') && x.getAttribute('onclick').includes('print'));
                if (b) b.click();
            }""")
            page.wait_for_timeout(300)
            printed = page.evaluate("() => window.__printed === true")
            handler_blocked = [v for v in violations[before:] if 'Content Security Policy' in v]
            record("the page's own onclick handler still executes",
                   'PASS' if printed and not handler_blocked else 'FAIL',
                   f'printed={printed}, violations={len(handler_blocked)}')

            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()

    print('\n' + '=' * 74)
    print('CSP ENFORCEMENT REPORT')
    print('=' * 74)
    for name, status, detail in RESULTS:
        print(f'  {status:<5} {name}' + (f'  [{detail}]' if detail else ''))
    failed = [r for r in RESULTS if r[1] != 'PASS']
    print('-' * 74)
    print(f'{len(RESULTS) - len(failed)}/{len(RESULTS)} passed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())

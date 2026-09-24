"""UI regression guards — the defects the person actually reported.

Every check here failed on the shipped build and passes now. They exist because
the previous suites measured the wrong thing: one counted iframes without ever
looking inside them, which is how a grid that rendered the whole application
into every card, and then cropped the QR out of view, passed 23/23.

Run:  python tests/e2e/TEST_UI_REGRESSIONS.py
"""
import os, re, sys, time, html, json, sqlite3, tempfile, subprocess, pathlib
import urllib.request, urllib.parse, http.cookiejar

ROOT = pathlib.Path(__file__).resolve().parents[2]
PORT = os.environ.get('UI_PORT', '8903')
BASE = f'http://127.0.0.1:{PORT}'
ADMIN_PW = 'TestAdmin@12345'
NEW_PW = 'RotatedPw#2026x'
RESULTS = []


def record(name, status, detail=''):
    RESULTS.append((name, status, detail))
    print(f'[{status}] {name}' + (f' — {detail}' if detail else ''))


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('BLOCKED: playwright not installed'); return 2

    td = tempfile.mkdtemp(prefix='ui_')
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

        LONG_NAME = 'المستشفى العسكري بدمياط الجديدة'
        con = sqlite3.connect(os.path.join(td, 'hr_central.db'))
        con.execute("INSERT INTO settings(key,value) VALUES('company_name',?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (LONG_NAME,))
        for i in range(1, 7):
            con.execute("INSERT OR IGNORE INTO employees(emp_code,name,department,job,status,updated_at)"
                        " VALUES(?,?,?,?,?,datetime('now'))",
                        (f'U{i:03d}', f'موظف رقم {i}', 'التمريض', 'ممرض', 'على رأس العمل'))
        con.commit(); con.close()

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_context(viewport={'width': 1400, 'height': 950}).new_page()
            errors = []
            page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)

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

            # ---------------------------------------------- ONE SHELL ----
            shells = {}
            for path in ('/', '/employees', '/users', '/id-cards'):
                page.goto(BASE + path, wait_until='domcontentloaded')
                page.wait_for_timeout(900)
                shells[path] = page.evaluate('''() => {
                    const a = document.querySelector('aside.side');
                    if (!a) return null;
                    return {
                        tag: (a.querySelector('.brand-info small') || {}).textContent || '',
                        items: [...a.querySelectorAll('.nav a')].map(x => x.textContent.trim()),
                    };
                }''')
            tags = {p: (s or {}).get('tag', '') for p, s in shells.items()}
            record('every page renders the same brand subtitle',
                   'PASS' if len(set(tags.values())) == 1 and all(tags.values()) else 'FAIL',
                   '; '.join(f'{k}={v}' for k, v in tags.items())[:120])

            navs = {p: tuple((s or {}).get('items', [])) for p, s in shells.items()}
            record('every page renders the same navigation',
                   'PASS' if len(set(navs.values())) == 1 else 'FAIL',
                   f'{len(set(navs.values()))} distinct menus across 4 pages')
            if len(set(navs.values())) > 1:
                base = navs['/employees']
                for pth, items in navs.items():
                    if items != base:
                        only_here = [x for x in items if x not in base]
                        missing = [x for x in base if x not in items]
                        print(f'      {pth}: extra={only_here[:4]} missing={missing[:4]}')

            first = next(iter(navs.values()))
            dupes = [x for x in set(first) if x and first.count(x) > 1]
            record('no duplicated sidebar entries', 'PASS' if not dupes else 'FAIL', f'{dupes[:3]}')

            # ------------------------------------- BRAND NOT TRUNCATED ---
            page.goto(BASE + '/users', wait_until='domcontentloaded')
            page.wait_for_timeout(700)
            brand = page.evaluate('''() => {
                const b = document.querySelector('.brand-info b');
                if (!b) return null;
                return {text: b.textContent.trim(), clipped: b.scrollWidth > b.clientWidth + 2};
            }''')
            record('hospital name is rendered in full, not ellipsised',
                   'PASS' if brand and brand['text'] == LONG_NAME and not brand['clipped'] else 'FAIL',
                   f"clipped={brand and brand['clipped']}")

            # ---------------------------------- SEARCH / KBD OVERLAP -----
            overlap = page.evaluate('''() => {
                const i = document.querySelector('.gsearch input');
                const k = document.querySelector('.gsearch kbd');
                if (!i || !k) return null;
                const ri = i.getBoundingClientRect(), rk = k.getBoundingClientRect();
                const cs = getComputedStyle(i);
                const padStart = parseFloat(cs.paddingInlineStart), padEnd = parseFloat(cs.paddingInlineEnd);
                return {
                    fits: ri.width <= i.parentElement.getBoundingClientRect().width + 1,
                    reserved: Math.max(padStart, padEnd) >= rk.width,
                };
            }''')
            record('search box fits the sidebar and reserves room for the Ctrl K badge',
                   'PASS' if overlap and overlap['fits'] and overlap['reserved'] else 'FAIL',
                   str(overlap))

            # --------------------------------- CARDS HAVE NO APP CHROME --
            page.goto(BASE + '/id-cards', wait_until='domcontentloaded')
            page.wait_for_timeout(2500)
            frames = [f for f in page.frames if '/id-card/' in f.url]
            record('ID card grid renders one frame per employee',
                   'PASS' if len(frames) >= 6 else 'FAIL', f'{len(frames)} frames')
            chrome = [f.locator('aside.side').count() for f in frames[:4]]
            record('no card embeds the application sidebar',
                   'PASS' if not any(chrome) else 'FAIL', f'sidebars per card={chrome}')

            # ------------------------------------------ GENERATE QR ------
            btn = page.locator('form[action="/qr/generate-all"] button')
            record('bulk QR control is present', 'PASS' if btn.count() else 'FAIL')
            if btn.count():
                btn.first.click()
                page.wait_for_load_state('domcontentloaded')
                for _ in range(90):
                    t = page.locator('#jobStatus').inner_text() if page.locator('#jobStatus').count() else ''
                    if 'اكتملت' in t or 'فشل' in t:
                        break
                    page.wait_for_timeout(500)
                record('bulk QR job completes', 'PASS' if 'اكتملت' in t else 'FAIL', t)

            # ------------------------- QR VISIBLE INSIDE THE GRID CARD ---
            # The defect: the card is authored at 860px, each grid frame is about
            # half that, and RTL layout starts from the right — so the QR column
            # was pushed outside the visible frame. It loaded fine (HTTP 200) and
            # was simply never on screen.
            page.goto(BASE + '/id-cards', wait_until='domcontentloaded')
            page.wait_for_timeout(3500)
            frames = [f for f in page.frames if '/id-card/' in f.url]
            visible = []
            for f in frames[:4]:
                info = f.evaluate('''() => {
                    const img = document.querySelector('img[alt="QR"]');
                    if (!img) return {present: false};
                    const r = img.getBoundingClientRect();
                    return {
                        present: true, loaded: img.naturalWidth > 0,
                        w: Math.round(r.width), h: Math.round(r.height),
                        inView: r.left >= -1 && r.top >= -1 &&
                                r.right <= document.documentElement.clientWidth + 1 &&
                                r.bottom <= document.documentElement.clientHeight + 1,
                    };
                }''')
                visible.append(info)
            ok = bool(visible) and all(v.get('present') and v.get('loaded') and
                                       v.get('inView') and v.get('w', 0) > 20 for v in visible)
            record('QR image is present, loaded AND fully inside the card frame',
                   'PASS' if ok else 'FAIL', json.dumps(visible[:2]))

            # The card must not overflow its frame in either axis.
            overflow = [f.evaluate('''() => {
                const c = document.querySelector('.id-card');
                if (!c) return null;
                const r = c.getBoundingClientRect();
                return {over_x: r.width > document.documentElement.clientWidth + 1,
                        over_y: r.height > document.documentElement.clientHeight + 1};
            }''') for f in frames[:3]]
            record('card does not overflow its frame',
                   'PASS' if all(o and not o['over_x'] and not o['over_y'] for o in overflow) else 'FAIL',
                   str(overflow[:2]))

            record('no JavaScript console errors across the flow',
                   'PASS' if not errors else 'FAIL', '; '.join(errors[:2])[:140])
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()

    print('\n' + '=' * 74)
    print('UI REGRESSION REPORT')
    print('=' * 74)
    for name, status, detail in RESULTS:
        print(f'  {status:<5} {name}' + (f'  [{detail}]' if detail else ''))
    failed = [r for r in RESULTS if r[1] != 'PASS']
    print('-' * 74)
    print(f'{len(RESULTS) - len(failed)}/{len(RESULTS)} passed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())

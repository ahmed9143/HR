"""Load benchmark — measured numbers only, never invented.

Seeds progressively larger datasets into the real database, drives the real
HTTP endpoints, and records p50/p95/p99 plus the server's own SQLite lock
telemetry from /health/deep.

IMPORTANT about the numbers this produces: they are measured on the machine
that runs the test. This is Linux with a warm page cache; production is a
Windows workstation where sqlite3.connect() is materially slower. Treat the
output as a *relative* scaling signal (does p95 degrade linearly or explode
between 500 and 5000 employees?), not as a production SLA. A Windows run is
still required before quoting any figure to a customer.

Run:  python tests/load/TEST_LOAD_BENCHMARK.py [--sizes 500,1000,5000]
"""
import os, re, sys, json, time, html, random, sqlite3, tempfile, statistics
import subprocess, pathlib, threading
import urllib.request, urllib.parse, urllib.error, http.cookiejar

ROOT = pathlib.Path(__file__).resolve().parents[2]
PORT = os.environ.get('LOAD_PORT', '8951')
BASE = f'http://127.0.0.1:{PORT}'
ADMIN_PW = 'TestAdmin@12345'
NEW_PW = 'RotatedPw#2026x'

DEPTS = ['Nursing', 'Surgery', 'Radiology', 'Pharmacy', 'Admin', 'ICU']
ROWS = []


def csrf_of(m):
    x = re.search(r'name="_csrf"[^>]*value="([^"]*)"', m)
    return html.unescape(x.group(1)) if x else ''


def seed(db_path, employees, attendance_per_employee):
    con = sqlite3.connect(db_path)
    con.execute('PRAGMA journal_mode=WAL')
    con.execute('PRAGMA synchronous=NORMAL')
    emps = [(f'L{i:06d}', f'Employee {i}', random.choice(DEPTS), 'Nurse', 'على رأس العمل')
            for i in range(employees)]
    con.executemany("INSERT OR IGNORE INTO employees(emp_code,name,department,job,status,updated_at)"
                    " VALUES(?,?,?,?,?,datetime('now'))", emps)
    con.commit()
    total_att = 0
    if attendance_per_employee:
        # Real column names: work_date (not date), plus UNIQUE(work_date,emp_code).
        # Dates must therefore be distinct per employee or the insert collides.
        from datetime import date as _date, timedelta as _td
        base = _date(2025, 1, 1)
        sql = ("INSERT OR IGNORE INTO attendance"
               "(work_date,emp_code,status,check_in,check_out,late_minutes,work_hours)"
               " VALUES(?,?,?,?,?,?,?)")
        batch = []
        for code, *_ in emps:
            for d in range(attendance_per_employee):
                batch.append(((base + _td(days=d)).isoformat(), code, 'حاضر',
                              '08:00', '16:00', d % 15, 8.0))
            if len(batch) >= 20000:
                con.executemany(sql, batch); total_att += len(batch); batch = []
        if batch:
            con.executemany(sql, batch); total_att += len(batch)
        con.commit()
        total_att = con.execute('SELECT COUNT(*) FROM attendance').fetchone()[0]
    con.close()
    return len(emps), total_att


def timed(fn, n):
    samples = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000)
    samples.sort()

    def pct(q):
        return round(samples[min(len(samples) - 1, int(round(q * (len(samples) - 1))))], 1)
    return {'n': n, 'p50': pct(.50), 'p95': pct(.95), 'p99': pct(.99),
            'max': round(samples[-1], 1)}


def run_size(employees, attendance_each, concurrency=8):
    td = tempfile.mkdtemp(prefix=f'load_{employees}_')
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
            print(f'  size={employees}: server never became ready'); return None

        jar = http.cookiejar.CookieJar()
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

        def get(p):
            return op.open(BASE + p, timeout=120).read().decode('utf-8', 'replace')

        def post(p, f):
            r = urllib.request.Request(BASE + p, data=urllib.parse.urlencode(f).encode(), method='POST')
            r.add_header('Content-Type', 'application/x-www-form-urlencoded')
            return op.open(r, timeout=300)

        lp = get('/login')
        post('/login', {'username': 'admin', 'password': ADMIN_PW, '_csrf': csrf_of(lp)})
        pwp = get('/password')
        post('/password', {'_csrf': csrf_of(pwp), 'current': ADMIN_PW,
                           'new_password': NEW_PW, 'confirm': NEW_PW})

        t0 = time.perf_counter()
        n_emp, n_att = seed(os.path.join(td, 'hr_central.db'), employees, attendance_each)
        seed_secs = round(time.perf_counter() - t0, 1)
        print(f'  size={employees}: seeded {n_emp} employees, {n_att} attendance rows in {seed_secs}s')

        db_bytes = os.path.getsize(os.path.join(td, 'hr_central.db'))

        measurements = {
            'dashboard':        timed(lambda: get('/'), 15),
            'employee_list':    timed(lambda: get('/employees'), 15),
            'employee_search':  timed(lambda: get('/employees?q=Employee+1'), 15),
            'employee_detail':  timed(lambda: get(f'/employee/profile/L{random.randint(0, employees-1):06d}'), 15),
            'operations_page':  timed(lambda: get('/employee/operations'), 10),
            'health_ready':     timed(lambda: get('/health/ready'), 20),
        }

        # Concurrent list reads — the shape that produced the original
        # "everything hangs" reports.
        errors = []
        latencies = []
        lock = threading.Lock()

        def worker():
            local_jar = http.cookiejar.CookieJar()
            lop = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(local_jar))
            lp2 = lop.open(BASE + '/login', timeout=30).read().decode()
            data = urllib.parse.urlencode({'username': 'admin', 'password': NEW_PW,
                                           '_csrf': csrf_of(lp2)}).encode()
            try:
                lop.open(urllib.request.Request(BASE + '/login', data=data, method='POST'), timeout=30)
            except Exception as e:
                with lock:
                    errors.append(repr(e))
                return
            for _ in range(10):
                t = time.perf_counter()
                try:
                    lop.open(BASE + '/employees', timeout=120).read()
                    with lock:
                        latencies.append((time.perf_counter() - t) * 1000)
                except Exception as e:
                    with lock:
                        errors.append(repr(e))

        threads = [threading.Thread(target=worker) for _ in range(concurrency)]
        wall0 = time.perf_counter()
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=600)
        wall = round(time.perf_counter() - wall0, 1)
        latencies.sort()

        def cpct(q):
            if not latencies:
                return None
            return round(latencies[min(len(latencies) - 1, int(round(q * (len(latencies) - 1))))], 1)

        concurrent = {'threads': concurrency, 'requests': len(latencies), 'wall_secs': wall,
                      'p50': cpct(.50), 'p95': cpct(.95), 'p99': cpct(.99),
                      'errors': len(errors)}

        # Bulk QR over the whole dataset — the heaviest background job.
        qr_secs = None
        qr_status = None
        idc = get('/id-cards')
        form = re.search(r'<form[^>]+action="/qr/generate-all"[^>]*>(.*?)</form>', idc, re.S)
        if form:
            q0 = time.perf_counter()
            r = post('/qr/generate-all', {'_csrf': csrf_of(form.group(1))})
            m = re.search(r'/jobs/([^/?#]+)', r.geturl())
            if m:
                for _ in range(2400):
                    st = json.loads(get(f'/employee/operations/job/{m.group(1)}'))
                    qr_status = st.get('status')
                    if qr_status in ('done', 'error', 'cancelled', 'timeout', 'timed_out'):
                        break
                    time.sleep(0.5)
                qr_secs = round(time.perf_counter() - q0, 1)

        deep = json.loads(get('/health/deep'))

        row = {
            'employees': employees,
            'attendance_rows': n_att,
            'db_mb': round(db_bytes / 1024 / 1024, 1),
            'seed_secs': seed_secs,
            'endpoints': measurements,
            'concurrent': concurrent,
            'bulk_qr_secs': qr_secs,
            'bulk_qr_status': qr_status,
            'sqlite_lock_waits': deep.get('sqlite', {}).get('lock_waits'),
            'sqlite_lock_seconds': deep.get('sqlite', {}).get('lock_seconds_total'),
            'slow_requests': deep.get('http', {}).get('slow_requests'),
            'rejected_503': deep.get('http', {}).get('rejected_503'),
            'threads': deep.get('threads'),
        }
        ROWS.append(row)
        return row
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except Exception:
            proc.kill()


def main():
    sizes = [500, 1000, 5000]
    att = {500: 200, 1000: 100, 5000: 20}   # ~100,000 attendance rows at each size
    for arg in sys.argv[1:]:
        if arg.startswith('--sizes'):
            sizes = [int(x) for x in arg.split('=', 1)[1].split(',')]

    print('=' * 78)
    print('LOAD BENCHMARK — measured on this host, Linux, warm cache')
    print('=' * 78)
    for size in sizes:
        print(f'\n--- {size} employees ---')
        row = run_size(size, att.get(size, 20))
        if not row:
            continue
        e = row['endpoints']
        print(f"  db={row['db_mb']} MB, attendance={row['attendance_rows']}")
        for name, m in e.items():
            print(f"    {name:<18} p50={m['p50']:>8} ms  p95={m['p95']:>8} ms  p99={m['p99']:>8} ms")
        c = row['concurrent']
        print(f"    concurrent x{c['threads']:<6} p50={c['p50']} ms  p95={c['p95']} ms  "
              f"errors={c['errors']}  wall={c['wall_secs']}s")
        print(f"    bulk QR: {row['bulk_qr_secs']}s ({row['bulk_qr_status']})")
        print(f"    sqlite lock waits={row['sqlite_lock_waits']} "
              f"({row['sqlite_lock_seconds']}s)  slow_requests={row['slow_requests']}  "
              f"503s={row['rejected_503']}")

    out = ROOT / 'docs' / 'LOAD_RESULTS.json'
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({'host': 'linux-container', 'note':
                               'Measured on Linux with warm cache. Windows will be slower; '
                               'use for relative scaling, not as an SLA.',
                               'results': ROWS}, indent=2), encoding='utf-8')
    print(f'\nRaw results -> {out.relative_to(ROOT)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

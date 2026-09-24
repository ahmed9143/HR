"""Dashboard cold-start — guards against the N+1 coming back.

The dashboard took 4.8 s on its first request with 5,000 employees and 18 ms
afterwards, which users experienced as a freeze every morning and after every
import. The cause was missing_documents_report() calling emp_allowed() once per
employee; emp_allowed() opened a fresh SQLite connection before it checked the
role, so rendering one page issued ~5,000 connections and ~30,000 statements.

This test asserts the shape of the fix, not a wall-clock number: the query count
must stay roughly constant as the dataset grows. A timing threshold would be
flaky across machines; a query count would not have passed before the fix and
cannot pass if the N+1 returns.

Run:  python tests/load/TEST_DASHBOARD_QUERIES.py
"""
import os, sys, time, sqlite3, tempfile, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.setdefault('HR_DATA_DIR', tempfile.mkdtemp(prefix='dashq_'))
os.environ.setdefault('HR_BOOTSTRAP_PASSWORD', 'TestAdmin@12345')
os.environ.setdefault('HR_NO_BROWSER', '1')

RESULTS = []


def record(name, status, detail=''):
    RESULTS.append((name, status, detail))
    print(f'[{status}] {name}' + (f' — {detail}' if detail else ''))


class Counter:
    """Counts connections and statements issued while rendering."""

    def __init__(self, server):
        self.server = server
        self.connects = 0
        self.statements = 0

    def __enter__(self):
        self._real_db = self.server.db
        counter = self

        class CountingConnection:
            """sqlite3.Connection attributes are read-only, so wrap instead."""

            def __init__(self, conn):
                object.__setattr__(self, '_conn', conn)

            def execute(self, *a, **k):
                counter.statements += 1
                return self._conn.execute(*a, **k)

            def executemany(self, *a, **k):
                counter.statements += 1
                return self._conn.executemany(*a, **k)

            def __getattr__(self, name):
                return getattr(self._conn, name)

        def counting_db():
            counter.connects += 1
            return CountingConnection(counter._real_db())

        self.server.db = counting_db
        return self

    def __exit__(self, *exc):
        self.server.db = self._real_db
        return False


class FakeHandler:
    path = '/'
    headers = {}
    client_address = ('127.0.0.1', 0)

    def __init__(self, user):
        self._user = user
        self.out = b''

    def send(self, body, *a, **k):
        self.out = body

    def require(self):
        return self._user

    def redirect(self, *a, **k):
        return None

    def forbid(self, *a, **k):
        return None


def seed(server, n):
    c = server.db()
    c.executemany("INSERT OR IGNORE INTO employees(emp_code,name,department,unit,job,status,updated_at)"
                  " VALUES(?,?,?,?,?,?,datetime('now'))",
                  [(f'Q{i:06d}', f'موظف {i}', 'التمريض', 'وحدة 1', 'ممرض', 'على رأس العمل')
                   for i in range(n)])
    c.commit(); c.close()


def main():
    import server as S
    S.init()
    # Required document categories are what makes the dashboard build the
    # report at all; without them the expensive path is skipped entirely and
    # the test would be vacuous.
    c = S.db()
    c.execute("INSERT INTO settings(key,value) VALUES('required_doc_categories',?) "
              "ON CONFLICT(key) DO UPDATE SET value=excluded.value", ('عقد,هوية,مؤهل',))
    c.commit(); c.close()
    S._SETTINGS_CACHE.clear()

    admin = {'username': 'admin', 'role': 'SuperAdmin', 'full_name': 'Admin',
             'scope_type': 'all', 'scope_value': '', 'csrf': 'x', '_sid': 's'}

    dashboard = getattr(S.H, 'dashboard', None)
    if dashboard is None:
        record('dashboard handler resolvable', 'FAIL', 'H.dashboard missing'); return 1
    record('dashboard handler resolvable', 'PASS')

    measurements = {}
    for n in (200, 2000):
        seed(S, n)
        S._SETTINGS_CACHE.clear(); S._ROLE_PERMS_CACHE.clear(); S._EMP_SCOPE_CACHE.clear()
        handler = FakeHandler(admin)
        with Counter(S) as counter:
            t0 = time.perf_counter()
            dashboard(handler, admin)
            elapsed = (time.perf_counter() - t0) * 1000
        measurements[n] = (counter.connects, counter.statements, elapsed)
        print(f'    {n:>5} employees: {counter.connects:>5} connections, '
              f'{counter.statements:>6} statements, {elapsed:7.0f} ms')

    c200, s200, t200 = measurements[200]
    c2000, s2000, t2000 = measurements[2000]

    record('connection count does not scale with employee count',
           'PASS' if c2000 <= c200 * 2 else 'FAIL',
           f'{c200} -> {c2000} for a 10x larger dataset')
    record('statement count does not scale with employee count',
           'PASS' if s2000 <= s200 * 2 else 'FAIL',
           f'{s200} -> {s2000} for a 10x larger dataset')
    record('connections stay far below one per employee',
           'PASS' if c2000 < 200 else 'FAIL', f'{c2000} connections for 2000 employees')

    # Cold and warm must now be the same: the fix removes the work rather than
    # caching it, so a cache miss can no longer produce a multi-second request.
    S._EMP_SCOPE_CACHE.clear(); S._SETTINGS_CACHE.clear()
    h = FakeHandler(admin)
    t0 = time.perf_counter(); dashboard(h, admin); cold = (time.perf_counter() - t0) * 1000
    t0 = time.perf_counter(); dashboard(h, admin); warm = (time.perf_counter() - t0) * 1000
    ratio = cold / max(warm, 0.1)
    record('cold request is not dramatically slower than a warm one',
           'PASS' if ratio < 5 else 'FAIL', f'cold={cold:.0f}ms warm={warm:.0f}ms ratio={ratio:.1f}x')

    # Guard the specific regression: the role must be decided before any lookup.
    src = (ROOT / 'server.py').read_text(encoding='utf-8')
    body = src[src.index('def emp_allowed(u,code):'):][:900]
    role_pos = body.find("u.get('role') in ('SuperAdmin','Admin','HR')")
    db_pos = body.find('c=db()')
    record('emp_allowed decides by role before touching the database',
           'PASS' if 0 <= role_pos < db_pos else 'FAIL',
           f'role check at {role_pos}, db() at {db_pos}')

    print('\n' + '=' * 74)
    print('DASHBOARD QUERY-COUNT REPORT')
    print('=' * 74)
    for name, status, detail in RESULTS:
        print(f'  {status:<5} {name}' + (f'  [{detail}]' if detail else ''))
    failed = [r for r in RESULTS if r[1] != 'PASS']
    print('-' * 74)
    print(f'{len(RESULTS) - len(failed)}/{len(RESULTS)} passed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())

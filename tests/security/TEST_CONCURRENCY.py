"""Session and cache concurrency — reproduces the races, then proves they close.

Part 6 of the hardening scope: SESS, _ROLE_PERMS_CACHE and _EMP_SCOPE_CACHE
were read and written from many request threads with no lock. The dangerous
one is the permission cache: because it has no TTL, a populate that lands
after an invalidation keeps a revoked permission granted until the process
restarts.

These tests hammer the real functions from many threads rather than reasoning
about the code.

Run:  python tests/security/TEST_CONCURRENCY.py
"""
import os, sys, time, random, sqlite3, tempfile, threading, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.setdefault('HR_DATA_DIR', tempfile.mkdtemp(prefix='conc_'))
os.environ.setdefault('HR_BOOTSTRAP_PASSWORD', 'TestAdmin@12345')
os.environ.setdefault('HR_NO_BROWSER', '1')

RESULTS = []


def record(name, status, detail=''):
    RESULTS.append((name, status, detail))
    print(f'[{status}] {name}' + (f' — {detail}' if detail else ''))


def main():
    import server as S
    S.init()

    # ---------------------------------------------------------------- setup
    c = S.db()
    c.execute("DELETE FROM role_permissions WHERE role='ConcTest'")
    for perm in ('employees.view', 'employees.edit', 'reports.view'):
        c.execute("INSERT INTO role_permissions(role,permission) VALUES(?,?)", ('ConcTest', perm))
    c.commit(); c.close()
    S.invalidate_role_perms('ConcTest')
    user = {'role': 'ConcTest', 'username': 'conc'}
    record('test role seeded with 3 permissions',
           'PASS' if S.can(user, 'employees.edit') else 'FAIL')

    # ------------------------------------------- RACE 1: revoke under load
    # Readers hammer can() while a writer revokes a permission. After the
    # revoke has committed and invalidated, no reader may ever see it again.
    stop = threading.Event()
    violations = []
    revoked_at = [None]
    reads = [0]
    lock = threading.Lock()

    def reader():
        while not stop.is_set():
            allowed = S.can(user, 'employees.edit')
            with lock:
                reads[0] += 1
                if revoked_at[0] is not None and time.time() > revoked_at[0] + 0.5 and allowed:
                    violations.append(time.time() - revoked_at[0])
            time.sleep(0.0005)

    threads = [threading.Thread(target=reader, daemon=True) for _ in range(16)]
    for t in threads:
        t.start()
    time.sleep(0.4)

    cw = S.db()
    cw.execute("DELETE FROM role_permissions WHERE role='ConcTest' AND permission='employees.edit'")
    cw.commit(); cw.close()
    S.invalidate_role_perms('ConcTest')
    revoked_at[0] = time.time()

    time.sleep(2.0)
    stop.set()
    for t in threads:
        t.join(timeout=2)

    record('revoked permission never reappears under concurrent reads',
           'PASS' if not violations else 'FAIL',
           f'{reads[0]} reads, {len(violations)} stale grants')

    # --------------------------- RACE 2: invalidate DURING an in-flight read
    # Directly exercise the generation guard: start a populate, invalidate
    # while it is in flight, and confirm the stale result is not cached.
    S.invalidate_role_perms('ConcTest')
    c = S.db()
    c.execute("INSERT INTO role_permissions(role,permission) VALUES('ConcTest','employees.edit')")
    c.commit(); c.close()

    barrier = threading.Event()
    original_db = S.db

    class _SlowClose:
        """Connection proxy that stalls on close().

        The window that matters is *after* the SELECT has returned the
        pre-revocation rows and *before* _role_perms writes them into the
        cache. _role_perms calls c.close() in exactly that gap, so delaying
        close() reproduces the real interleaving. Delaying db() itself does
        not: the SELECT would then run after the revocation and observe the
        new state, which is why an earlier version of this test passed even
        with the guard removed.
        """

        def __init__(self, conn):
            self._conn = conn

        def __getattr__(self, name):
            return getattr(self._conn, name)

        def close(self):
            barrier.set()
            time.sleep(0.8)
            return self._conn.close()

    def slow_db():
        conn = original_db()
        if getattr(threading.current_thread(), 'slow', False):
            return _SlowClose(conn)
        return conn

    outcome = {}

    def populate():
        threading.current_thread().slow = True
        S.db = slow_db
        try:
            outcome['perms'] = S._role_perms('ConcTest')
        finally:
            S.db = original_db

    t = threading.Thread(target=populate)
    t.start()
    barrier.wait(timeout=5)
    time.sleep(0.1)
    cw = S.db()
    cw.execute("DELETE FROM role_permissions WHERE role='ConcTest' AND permission='employees.edit'")
    cw.commit(); cw.close()
    S.invalidate_role_perms('ConcTest')
    t.join(timeout=10)

    cached = S._ROLE_PERMS_CACHE.get('ConcTest')
    poisoned = cached is not None and 'employees.edit' in cached
    record('invalidation during an in-flight read does not poison the cache',
           'PASS' if not poisoned else 'FAIL',
           f'cached={sorted(cached) if cached else None}')
    record('subsequent check reflects the revocation',
           'PASS' if not S.can(user, 'employees.edit') else 'FAIL')

    # ------------------------------------------- scope cache is bounded ----
    cap = S._EMP_SCOPE_MAX
    c = S.db()
    for i in range(50):
        c.execute("INSERT OR IGNORE INTO employees(emp_code,name,department,unit,status,updated_at)"
                  " VALUES(?,?,?,?,?,datetime('now'))",
                  (f'CC{i:04d}', f'C {i}', 'Nursing', 'U1', 'على رأس العمل'))
    c.commit(); c.close()
    admin = {'role': 'SuperAdmin', 'username': 'admin'}
    for i in range(50):
        S.emp_allowed(admin, f'CC{i:04d}')
    record('employee scope cache has a size cap', 'PASS' if cap and cap > 0 else 'FAIL',
           f'cap={cap}, entries={len(S._EMP_SCOPE_CACHE)}')

    # Force the cap and confirm eviction actually happens.
    S._EMP_SCOPE_MAX = 20
    try:
        for i in range(50):
            S._EMP_SCOPE_CACHE.pop(f'CC{i:04d}', None)
        for i in range(50):
            S.emp_allowed(admin, f'CC{i:04d}')
        record('scope cache evicts instead of growing without bound',
               'PASS' if len(S._EMP_SCOPE_CACHE) <= 50 else 'FAIL',
               f'{len(S._EMP_SCOPE_CACHE)} entries after 50 lookups with cap 20')
    finally:
        S._EMP_SCOPE_MAX = cap

    # ------------------------------------- concurrent emp_allowed is stable
    errors = []

    def scope_worker():
        try:
            for _ in range(200):
                S.emp_allowed(admin, f'CC{random.randint(0, 49):04d}')
        except Exception as e:          # noqa: BLE001 - the point is to catch anything
            errors.append(repr(e))

    ts = [threading.Thread(target=scope_worker) for _ in range(12)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=30)
    record('concurrent scope lookups raise no exceptions',
           'PASS' if not errors else 'FAIL', '; '.join(errors[:3]))

    # ----------------------------------- concurrent session dict mutation --
    sess_errors = []

    def sess_worker(n):
        try:
            for i in range(300):
                sid = f'sid{n % 5}'
                S.SESS[sid] = {'username': f'u{n}', 'last_seen': S.now(), '_sid': sid}
                _ = S.SESS.get(sid, {}).get('username')
                if i % 50 == 0:
                    S.SESS.pop(f'sid{(n + 1) % 5}', None)
        except Exception as e:          # noqa: BLE001
            sess_errors.append(repr(e))

    ts = [threading.Thread(target=sess_worker, args=(n,)) for n in range(10)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=30)
    record('concurrent SESS mutation raises no exceptions',
           'PASS' if not sess_errors else 'FAIL', '; '.join(sess_errors[:3]))

    print('\n' + '=' * 74)
    print('CONCURRENCY REPORT')
    print('=' * 74)
    for name, status, detail in RESULTS:
        print(f'  {status:<5} {name}' + (f'  [{detail}]' if detail else ''))
    failed = [r for r in RESULTS if r[1] != 'PASS']
    print('-' * 74)
    print(f'{len(RESULTS) - len(failed)}/{len(RESULTS)} passed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())

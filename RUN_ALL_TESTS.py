"""Run the automated test suite and write docs/TEST_REPORT.md.

Used locally and by CI. Exits non-zero if any test fails.

Excluded by default, and why:
  tests/packaging/   needs a built executable — the build job runs it after
                     PyInstaller has produced one.
  TEST_LOAD_BENCHMARK  a measurement that prints numbers, not a pass/fail gate;
                     the regression gate for performance is TEST_DASHBOARD_QUERIES.

Usage:
  python RUN_ALL_TESTS.py              # full suite
  python RUN_ALL_TESTS.py security e2e # only these folders
"""
import os, sys, time, datetime, pathlib, subprocess

ROOT = pathlib.Path(__file__).resolve().parent
EXCLUDED_DIRS = {'packaging'}
EXCLUDED_FILES = {'TEST_LOAD_BENCHMARK.py'}
TIMEOUT = int(os.environ.get('HR_TEST_TIMEOUT', '900'))


def main():
    only = set(sys.argv[1:])
    env = dict(os.environ)
    env.setdefault('PYTHONUTF8', '1')
    env.setdefault('PYTHONIOENCODING', 'utf-8')
    env.setdefault('PYTHONDONTWRITEBYTECODE', '1')
    # The authorization test waits one cache TTL twice; keep that short in CI.
    env.setdefault('HR_ROLE_PERMS_TTL', '5')

    tests = []
    for path in sorted(ROOT.joinpath('tests').rglob('TEST_*.py')):
        group = path.parent.name
        if only and group not in only:
            continue
        if not only and (group in EXCLUDED_DIRS or path.name in EXCLUDED_FILES):
            continue
        tests.append(path)

    rows = []
    for path in tests:
        rel = path.relative_to(ROOT)
        t0 = time.time()
        try:
            r = subprocess.run([sys.executable, str(path)], cwd=ROOT, env=env,
                               capture_output=True, text=True, timeout=TIMEOUT,
                               encoding='utf-8', errors='replace')
            code, out = r.returncode, (r.stdout or '') + (r.stderr or '')
        except subprocess.TimeoutExpired as e:
            code, out = 124, f'TIMEOUT after {TIMEOUT}s'
        dur = round(time.time() - t0, 1)
        status = 'PASS' if code == 0 else 'FAIL'
        note = ''
        if status == 'FAIL':
            tail = [l for l in out.strip().splitlines() if l.strip()]
            note = (tail[-1] if tail else f'exit {code}')[:200]
            print(f'[FAIL] {rel}  ({dur}s)\n       {note}', flush=True)
            # Show the full failing output in CI logs, not just the last line.
            print('\n'.join(out.strip().splitlines()[-40:]), flush=True)
        else:
            print(f'[PASS] {rel}  ({dur}s)', flush=True)
        rows.append((str(rel).replace('\\', '/'), status, dur, note))

    passed = sum(1 for r in rows if r[1] == 'PASS')
    lines = ['# Automated Test Report', '',
             f'Generated: {datetime.datetime.now().isoformat(timespec="seconds")}',
             f'Platform: {sys.platform} · Python {sys.version.split()[0]}', '',
             f'**{passed}/{len(rows)} passed**', '',
             '| Test | Result | Time | Note |', '|---|---|---|---|']
    lines += [f'| `{n}` | {s} | {d}s | {t} |' for n, s, d, t in rows]
    (ROOT / 'docs').mkdir(exist_ok=True)
    (ROOT / 'docs' / 'TEST_REPORT.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'\n{passed}/{len(rows)} passed -> docs/TEST_REPORT.md')
    return 0 if rows and passed == len(rows) else 1


if __name__ == '__main__':
    sys.exit(main())

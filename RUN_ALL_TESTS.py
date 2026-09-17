"""Run every test in tests/ and write docs/TEST_REPORT.md."""
import subprocess, sys, pathlib, time, datetime, re
ROOT = pathlib.Path(__file__).resolve().parent
rows = []
for path in sorted(ROOT.joinpath('tests').rglob('TEST_*.py')):
    rel = path.relative_to(ROOT)
    t0 = time.time()
    r = subprocess.run([sys.executable, str(path)], cwd=ROOT,
                       capture_output=True, text=True, timeout=600)
    dur = time.time() - t0
    status = 'PASS' if r.returncode == 0 else 'FAIL'
    note = ''
    if status == 'FAIL':
        combined = (r.stdout + r.stderr).strip()
        lines = combined.splitlines()
        # Prefer the specific failing/erroring assertion lines a test's own
        # report prints (e.g. "[FAIL] ..." / "[ERR ] ..."), and any traceback,
        # over the generic summary/border line that happens to be last.
        flagged = [ln for ln in lines if re.search(r'\[FAIL\]|\[ERR\s*\]|Traceback|Error:|Exception', ln)]
        if flagged:
            note = ' | '.join(flagged)[:300]
        else:
            note = lines[-1][:160] if lines else f'exit {r.returncode}'
        print(f'----- captured output: {rel} -----')
        print(combined[-4000:])
        print(f'----- end output: {rel} -----')
    rows.append((str(rel), status, round(dur, 1), note))
    print(f'[{status}] {rel}  ({dur:.1f}s)')

passed = sum(1 for r in rows if r[1] == 'PASS')
out = [f'# Automated Test Report', '',
       f'Generated: {datetime.datetime.now().isoformat(timespec="seconds")}',
       f'Python: {sys.version.split()[0]}', '',
       f'**{passed}/{len(rows)} passed**', '',
       '| Test | Result | Time | Note |', '|---|---|---|---|']
for name, status, dur, note in rows:
    out.append(f'| `{name}` | {status} | {dur}s | {note} |')
ROOT.joinpath('docs').mkdir(exist_ok=True)
ROOT.joinpath('docs', 'TEST_REPORT.md').write_text('\n'.join(out) + '\n', encoding='utf-8')
print(f'\n{passed}/{len(rows)} passed -> docs/TEST_REPORT.md')
sys.exit(0 if passed == len(rows) else 1)

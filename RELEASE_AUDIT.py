"""Release-safety gate. Run before packaging; a non-zero exit means DO NOT SHIP."""
import pathlib, re, sys
root = pathlib.Path(__file__).resolve().parent
issues = []

for p in root.rglob('*'):
    if not p.is_file() or '__pycache__' in p.parts:
        continue
    rel = p.relative_to(root)
    name = p.name
    if re.search(r'raw_export|_109|REAL', name, re.I):
        issues.append(f'possible real employee PII: {rel}')
    if p.suffix in ('.db', '.sqlite', '.sqlite3'):
        issues.append(f'database shipped: {rel}')
    if p.suffix in ('.pem', '.key') or name in ('INITIAL_ADMIN_PASSWORD.txt', 'backup.key'):
        issues.append(f'secret shipped: {rel}')
    if name.startswith('HR_Backup_'):
        issues.append(f'backup archive shipped: {rel}')
    if p.suffix == '.pyc':
        issues.append(f'bytecode shipped: {rel}')
    if p.suffix == '.bak':
        issues.append(f'stale source copy shipped: {rel}')
    if p.suffix in ('.py', '.md', '.txt', '.bat'):
        text = p.read_text(encoding='utf-8', errors='ignore')
        # Match the removed credential only as a standalone value, so the test
        # credential TestAdmin@12345 and the changelog entry do not trip this.
        if re.search(r"(?<!Test)Admin@12345", text) and rel.name not in ('CHANGELOG.md', 'RELEASE_AUDIT.py'):
            issues.append(f'removed default credential referenced: {rel}')

for d in root.rglob('__pycache__'):
    issues.append(f'pycache shipped: {d.relative_to(root)}')

print('=' * 70)
print('RELEASE SAFETY AUDIT')
print('=' * 70)
if issues:
    for i in issues:
        print('  [BLOCK]', i)
    print(f'\n{len(issues)} blocking issue(s). DO NOT SHIP.')
    sys.exit(1)
print('  CLEAN — no real PII, no database, no secrets, no backup archives,')
print('          no bytecode, no stale sources, no default credential.')
sys.exit(0)

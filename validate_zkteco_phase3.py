"""
Offline validation for ZKTeco Phase 3 (ACCDB reader + name-matching report).

Reads the REAL uploaded ACCDB (read-only -- never writes to it) to confirm
the reader works against actual data, but all "matching" and "apply" tests
run against synthetic in-memory employees / a throwaway SQLite DB, never a
real HR database.

Run: python3 validate_zkteco_phase3.py /path/to/New_Microsoft_Access_Database.accdb
"""
import sys, os, sqlite3, tempfile, csv

RESULTS = []
def check(name, cond):
    RESULTS.append((name, bool(cond)))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")

def main():
    accdb_path = sys.argv[1] if len(sys.argv) > 1 else \
        "/mnt/user-data/uploads/New_Microsoft_Access_Database.accdb"

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from zkteco_accdb_import import (
        read_accdb_users, normalize_arabic_name, build_match_report,
        write_report_csv, apply_confirmed_mappings, AccdbReadError
    )

    before_mtime = os.path.getmtime(accdb_path)
    before_size = os.path.getsize(accdb_path)

    # --- real file read ---
    users = read_accdb_users(accdb_path)
    check("read_accdb_users returns 404 rows from the real file", len(users) == 404)
    check("every row has a non-empty badge_number", all(u['badge_number'] for u in users))
    check("every row has a non-empty name", all(u['name'] for u in users))
    check("badge_numbers are all unique", len({u['badge_number'] for u in users}) == 404)

    after_mtime = os.path.getmtime(accdb_path)
    after_size = os.path.getsize(accdb_path)
    check("ACCDB file untouched (size unchanged)", before_size == after_size)
    check("ACCDB file untouched (mtime unchanged)", before_mtime == after_mtime)

    # --- normalization sanity ---
    check("normalize_arabic_name unifies alef variants", normalize_arabic_name("أحمد") == normalize_arabic_name("احمد"))
    check("normalize_arabic_name unifies ta-marbuta/ha", normalize_arabic_name("فاطمة") == normalize_arabic_name("فاطمه"))
    check("normalize_arabic_name strips diacritics", normalize_arabic_name("مُحَمَّد") == normalize_arabic_name("محمد"))

    # --- matching against synthetic employees (uses 3 REAL names from the file
    #     on purpose, to prove matching works on real Arabic strings, but the
    #     "employees" list itself is synthetic / made up emp_codes) ---
    real_sample = users[:3]
    synthetic_employees = [
        {'emp_code': 'SYN-001', 'name': real_sample[0]['name'], 'zk_user_id': None},
        {'emp_code': 'SYN-002', 'name': real_sample[1]['name'] + ' ', 'zk_user_id': None},  # trailing space variant
        {'emp_code': 'SYN-003', 'name': 'اسم لا يطابق اي حد في الملف تماما', 'zk_user_id': None},
        {'emp_code': 'SYN-004', 'name': 'موظف مرتبط بالفعل', 'zk_user_id': real_sample[2]['badge_number']},
    ]
    report = build_match_report(real_sample, synthetic_employees)
    check("match report has 3 rows (one per accdb user given)", len(report) == 3)

    row0 = next(r for r in report if r['badge_number'] == real_sample[0]['badge_number'])
    check("exact name match -> status=exact, correct emp_code", row0['status'] == 'exact' and row0['suggested_emp_code'] == 'SYN-001')

    row1 = next(r for r in report if r['badge_number'] == real_sample[1]['badge_number'])
    check("near-identical (whitespace) match -> status=exact/fuzzy with correct emp_code", row1['status'] in ('exact', 'fuzzy') and row1['suggested_emp_code'] == 'SYN-002')

    row2 = next(r for r in report if r['badge_number'] == real_sample[2]['badge_number'])
    check("already-linked badge -> status=already_linked, no guessing", row2['status'] == 'already_linked' and row2['suggested_emp_code'] == 'SYN-004')

    # --- a name with genuinely no match must report status=none, not a bad guess ---
    fake_user = [{'badge_number': 'ZZZZ', 'name': 'اسم غريب تماما غير موجود ابدا', 'dept_id': '1'}]
    only_unrelated_employee = [{'emp_code': 'SYN-999', 'name': 'شخص مختلف كليا', 'zk_user_id': None}]
    none_report = build_match_report(fake_user, only_unrelated_employee, min_score=0.9)
    check("no-match case returns status=none (no forced suggestion)", none_report[0]['status'] == 'none')

    # --- CSV round-trip ---
    tmp_csv = tempfile.NamedTemporaryFile(suffix='.csv', delete=False).name
    write_report_csv(report, tmp_csv)
    with open(tmp_csv, encoding='utf-8-sig') as f:
        read_back = list(csv.DictReader(f))
    check("CSV round-trips same row count", len(read_back) == len(report))
    check("CSV preserves Arabic text", any(r['accdb_name'] == real_sample[0]['name'] for r in read_back))

    # --- apply_confirmed_mappings against a THROWAWAY sqlite DB, never a real one ---
    tmp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False).name
    conn = sqlite3.connect(tmp_db)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE employees (emp_code TEXT PRIMARY KEY, name TEXT, zk_user_id TEXT UNIQUE, updated_at TEXT)")
    conn.execute("INSERT INTO employees (emp_code, name) VALUES ('SYN-001', ?)", (real_sample[0]['name'],))
    conn.execute("INSERT INTO employees (emp_code, name, zk_user_id) VALUES ('SYN-004', 'x', ?)", (real_sample[2]['badge_number'],))
    conn.commit(); conn.close()

    # mark only row0 confirmed
    for r in read_back:
        r['confirm'] = '1' if r['badge_number'] == real_sample[0]['badge_number'] else ''
    fieldnames = ['badge_number', 'accdb_name', 'dept_id', 'suggested_emp_code', 'suggested_name', 'match_score', 'status', 'confirm']
    with open(tmp_csv, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames); w.writeheader()
        for r in read_back: w.writerow(r)

    def _db():
        c = sqlite3.connect(tmp_db); c.row_factory = sqlite3.Row; return c
    fake_globals = {'db': _db, 'now': lambda: '2026-08-28T00:00:00'}

    result = apply_confirmed_mappings(fake_globals, tmp_csv)
    check("apply_confirmed_mappings applies exactly 1 row (only one confirmed)", result['applied'] == 1)
    check("apply_confirmed_mappings skips unconfirmed rows", result['skipped_not_confirmed'] == len(read_back) - 1)

    c = _db()
    updated = c.execute("SELECT zk_user_id FROM employees WHERE emp_code='SYN-001'").fetchone()
    check("SYN-001.zk_user_id was actually set to the confirmed badge", updated['zk_user_id'] == real_sample[0]['badge_number'])
    unrelated = c.execute("SELECT zk_user_id FROM employees WHERE emp_code='SYN-004'").fetchone()
    check("SYN-004 (pre-existing link, untouched row) unchanged", unrelated['zk_user_id'] == real_sample[2]['badge_number'])
    c.close()

    # --- applying the SAME confirmed csv again must not error (idempotent-ish: no dup writes, no crash) ---
    result2 = apply_confirmed_mappings(fake_globals, tmp_csv)
    check("re-applying same confirmed CSV doesn't crash", result2['applied'] == 1 and not result2['errors'])

    os.unlink(tmp_csv); os.unlink(tmp_db)

    # --- error path: nonexistent table name ---
    try:
        read_accdb_users(accdb_path, table_name='DoesNotExist')
        check("reading a nonexistent table raises AccdbReadError", False)
    except AccdbReadError:
        check("reading a nonexistent table raises AccdbReadError", True)

    passed = sum(1 for _, ok in RESULTS if ok)
    total = len(RESULTS)
    print(f"\n{passed}/{total} PASS")
    if passed != total:
        sys.exit(1)

if __name__ == '__main__':
    main()

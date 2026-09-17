"""
Generates the ACCDB <-> employees name-match REVIEW report against the real
HR database. Run this ON THE MACHINE WHERE THE REAL hr_central.db LIVES
(or point HR_DATA_DIR at a copy of it). It only READS the database and the
ACCDB file; it writes nothing to either. Output is a CSV for a human to
review and mark 'confirm=1' before running apply_confirmed_mappings.

Usage:
    python3 run_accdb_match_report.py /path/to/New_Microsoft_Access_Database.accdb [output.csv]

If HR_DATA_DIR is not set, server.py's default data location is used (same
default the real app uses).
"""
import sys, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    accdb_path = sys.argv[1]
    out_path = sys.argv[2] if len(sys.argv) > 2 else 'zkteco_accdb_match_review.csv'

    from zkteco_accdb_import import read_accdb_users, build_match_report, write_report_csv

    print(f"Reading ACCDB: {accdb_path}")
    users = read_accdb_users(accdb_path)
    print(f"  -> {len(users)} badge/name rows found")

    import server
    c = server.db()
    try:
        rows = c.execute("SELECT emp_code, name, zk_user_id FROM employees").fetchall()
        employees = [{'emp_code': r['emp_code'], 'name': r['name'], 'zk_user_id': r['zk_user_id']} for r in rows]
    finally:
        c.close()
    print(f"Loaded {len(employees)} employees from the real HR database (read-only)")

    already = sum(1 for e in employees if e['zk_user_id'])
    print(f"  -> {already} already have a zk_user_id linked")

    report = build_match_report(users, employees)
    write_report_csv(report, out_path)

    exact = sum(1 for r in report if r['status'] == 'exact')
    fuzzy = sum(1 for r in report if r['status'] == 'fuzzy')
    none_ = sum(1 for r in report if r['status'] == 'none')
    linked = sum(1 for r in report if r['status'] == 'already_linked')

    print(f"\nReport written to: {out_path}")
    print(f"  exact matches:     {exact}")
    print(f"  fuzzy matches:     {fuzzy}  (REVIEW these carefully)")
    print(f"  no match found:    {none_}")
    print(f"  already linked:    {linked}")
    print(f"\nNothing was written to the database. To apply confirmed rows:")
    print(f"  1. Open {out_path}, put '1' in the 'confirm' column for rows you approve")
    print(f"  2. Run: python3 -c \"import server; from zkteco_accdb_import import apply_confirmed_mappings; "
          f"print(apply_confirmed_mappings(server.__dict__, '{out_path}'))\"")


if __name__ == '__main__':
    main()

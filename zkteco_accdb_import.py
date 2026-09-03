# ZKTeco Integration — Phase 3: ACCDB reader / employee-mapping tool.
#
# What the ACCDB actually is (VERIFIED by opening it, not guessed):
#   A single table, "Table1" (404 rows), matching the classic ZKTeco/eSSL
#   "Attendance Management System" USERINFO export schema: Badgenumber,
#   SSN, Name, DEFAULTDEPTID, CardNo, VERIFICATIONMETHOD, privilege, plus a
#   set of per-employee attendance-rule flags (ATT/INLATE/OUTEARLY/OVERTIME/
#   SEP/HOLIDAY/LUNCHDURATION/TimeZone1-3/...). It is employee MASTER data
#   from the attendance software's own database, not a punch/attendance log
#   -- there is no CHECKINOUT-style table in this file, only one table.
#
#   Confirmed field facts (from the real file, all 404 rows):
#     - Badgenumber: 404/404 populated, ALL UNIQUE. This is the device-side
#       user ID -- i.e. exactly what employees.zk_user_id should hold once
#       an employee is matched.
#     - Name: 404/404 populated, Arabic. This is display/matching-hint data
#       only (per the Phase 1 rule already in force: names are NEVER the
#       matching key for real linking -- only used to help a human confirm).
#     - CardNo: 0/404 populated (all empty) -- not usable.
#     - SSN, BIRTHDAY, HIREDDAY, street/CITY/STATE/ZIP, OPHONE/FPHONE: all
#       empty in every row -- this export has no PII beyond name + badge.
#     - DEFAULTDEPTID: populated (35 distinct department IDs), but this file
#       contains no department-name lookup table, so IDs alone are not
#       resolvable to Arabic department names from this file.
#
# Reader: uses `access_parser` (pure-Python PyPI package, no ODBC/mdbtools
# system dependency required), confirmed against this exact file and
# cross-checked byte-for-byte against `mdb-export` (mdbtools) output for
# parity. If access_parser is not installed, this module tells the caller
# clearly rather than silently failing.
#
# ---------------------------------------------------------------------------
# Matching policy (hard rule, matches what was already agreed for Phase 1/2):
#   This module NEVER writes to employees.zk_user_id automatically based on
#   name similarity. It only ever produces a REVIEW report. A human (Ahmed /
#   an HR admin) must confirm each match; apply_confirmed_mappings() only
#   accepts rows a human has explicitly marked "confirm=1" in the reviewed
#   CSV, and even then will not overwrite an employee that already has a
#   zk_user_id unless force=True is passed row-by-row understanding.
# ---------------------------------------------------------------------------

import csv
import re
import difflib


class AccdbReadError(Exception):
    pass


# Arabic normalization for matching only (never for storage/display) --
# collapses common orthographic variants so "أحمد"/"احمد" or
# alef-maksura/yaa compare equal, and strips tashkeel + punctuation/extra
# whitespace.
_ARABIC_DIACRITICS = re.compile(r'[\u0617-\u061A\u064B-\u0652\u0670\u06D6-\u06ED]')
_TATWEEL = '\u0640'


def normalize_arabic_name(name):
    if not name:
        return ''
    s = name.strip()
    s = _ARABIC_DIACRITICS.sub('', s)
    s = s.replace(_TATWEEL, '')
    s = s.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا')
    s = s.replace('ى', 'ي')
    s = s.replace('ة', 'ه')
    s = re.sub(r'\s+', ' ', s)
    return s.strip()


def read_accdb_users(accdb_path, table_name='Table1'):
    """Returns list[dict(badge_number, name, dept_id, raw)] from the ACCDB.
    Raises AccdbReadError with a clear message on any failure -- never
    partially returns guessed data."""
    try:
        from access_parser import AccessParser
    except ImportError:
        raise AccdbReadError(
            "The 'access_parser' package is not installed. Install with: "
            "pip install access_parser --break-system-packages"
        )
    try:
        db = AccessParser(accdb_path)
        if table_name not in db.catalog:
            raise AccdbReadError(
                f"Table '{table_name}' not found. Tables present: {sorted(db.catalog.keys())}"
            )
        cols = db.parse_table(table_name)
    except AccdbReadError:
        raise
    except Exception as e:
        raise AccdbReadError(f"Failed to read '{accdb_path}': {e}")

    if 'Badgenumber' not in cols or 'Name' not in cols:
        raise AccdbReadError(
            f"Expected columns Badgenumber/Name not found in '{table_name}'. "
            f"Columns present: {list(cols.keys())}"
        )

    n = len(cols['Badgenumber'])
    out = []
    for i in range(n):
        badge = (cols['Badgenumber'][i] or '').strip()
        name = (cols['Name'][i] or '').strip()
        if not badge:
            continue  # a row with no badge number can't be linked to a device identity at all
        dept = cols.get('DEFAULTDEPTID', [None] * n)[i]
        out.append({'badge_number': badge, 'name': name, 'dept_id': dept})
    return out


def build_match_report(accdb_users, employees, min_score=0.72):
    """
    employees: list[dict(emp_code, name, zk_user_id)] -- caller supplies this
    from the real HR database (this function does no DB access itself, so it
    is fully unit-testable offline with synthetic employees too).

    Returns list[dict] rows ready to write to a review CSV:
      badge_number, accdb_name, dept_id, suggested_emp_code, suggested_name,
      match_score, already_linked_to (if any employee already has this badge
      as zk_user_id), status ('exact'|'fuzzy'|'none'|'already_linked')

    This NEVER modifies the employees list or any database -- pure function.
    """
    by_zk = {e['zk_user_id']: e for e in employees if e.get('zk_user_id')}
    norm_employees = [(e, normalize_arabic_name(e.get('name', ''))) for e in employees]

    rows = []
    for u in accdb_users:
        badge = u['badge_number']
        already = by_zk.get(badge)
        if already:
            rows.append({
                'badge_number': badge, 'accdb_name': u['name'], 'dept_id': u['dept_id'],
                'suggested_emp_code': already['emp_code'], 'suggested_name': already['name'],
                'match_score': 1.0, 'status': 'already_linked', 'confirm': '',
            })
            continue

        target_norm = normalize_arabic_name(u['name'])
        best_emp, best_score = None, 0.0
        for emp, emp_norm in norm_employees:
            if emp.get('zk_user_id'):
                continue  # already linked to a different badge -- not a candidate
            if not emp_norm or not target_norm:
                continue
            score = difflib.SequenceMatcher(None, target_norm, emp_norm).ratio()
            if score > best_score:
                best_score, best_emp = score, emp

        if best_emp and best_score >= 0.999:
            status = 'exact'
        elif best_emp and best_score >= min_score:
            status = 'fuzzy'
        else:
            status = 'none'
            best_emp = None

        rows.append({
            'badge_number': badge, 'accdb_name': u['name'], 'dept_id': u['dept_id'],
            'suggested_emp_code': best_emp['emp_code'] if best_emp else '',
            'suggested_name': best_emp['name'] if best_emp else '',
            'match_score': round(best_score, 3) if best_emp else 0.0,
            'status': status, 'confirm': '',
        })
    return rows


def write_report_csv(rows, out_path):
    fieldnames = ['badge_number', 'accdb_name', 'dept_id', 'suggested_emp_code',
                  'suggested_name', 'match_score', 'status', 'confirm']
    with open(out_path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def apply_confirmed_mappings(g, csv_path, applied_by=None, force=False):
    """
    Reads a human-reviewed CSV (as produced by write_report_csv, then edited:
    a row is only applied if its 'confirm' column is exactly '1') and writes
    employees.zk_user_id for those rows. Additive only:
      - Never touches a row where confirm != '1'.
      - Never overwrites an employee that already has a different zk_user_id
        unless force=True.
      - Relies on the existing partial UNIQUE index (idx_employees_zk_user_id,
        from Phase 1) to reject a badge already linked to someone else --
        that failure is caught per-row and reported, not raised.

    Returns dict(applied, skipped_not_confirmed, skipped_already_has_id,
    skipped_conflict, errors=[...]).
    """
    db = g['db']
    result = {'applied': 0, 'skipped_not_confirmed': 0, 'skipped_already_has_id': 0,
              'skipped_conflict': 0, 'errors': []}

    with open(csv_path, encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))

    c = db()
    try:
        for r in rows:
            if r.get('confirm', '').strip() != '1':
                result['skipped_not_confirmed'] += 1
                continue
            emp_code = (r.get('suggested_emp_code') or '').strip()
            badge = (r.get('badge_number') or '').strip()
            if not emp_code or not badge:
                result['errors'].append(f"row missing emp_code/badge: {r}")
                continue

            existing = c.execute(
                'SELECT zk_user_id FROM employees WHERE emp_code=?', (emp_code,)
            ).fetchone()
            if existing is None:
                result['errors'].append(f"emp_code not found: {emp_code}")
                continue
            if existing['zk_user_id'] and existing['zk_user_id'] != badge and not force:
                result['skipped_already_has_id'] += 1
                continue

            try:
                now_fn = g.get('now')
                ts = now_fn() if now_fn else None
                if ts:
                    c.execute('UPDATE employees SET zk_user_id=?, updated_at=? WHERE emp_code=?', (badge, ts, emp_code))
                else:
                    c.execute('UPDATE employees SET zk_user_id=? WHERE emp_code=?', (badge, emp_code))
                c.commit()
                result['applied'] += 1
            except Exception as e:
                c.rollback()
                result['skipped_conflict'] += 1
                result['errors'].append(f"{emp_code} -> {badge}: {e}")
    finally:
        c.close()

    return result

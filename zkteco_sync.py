# ZKTeco Integration — Phase 2b: Sync engine.
#
# Scope: turn RawPunch objects (from zkteco_connector.py, real device or
# mock) into rows in zk_attendance_raw, idempotently, matched to employees
# via employees.zk_user_id ONLY (never by name). No UI, no background
# scheduler, no processing into the daily `attendance` table -- those are
# later phases. Nothing in this module runs at import time except table
# creation (same additive pattern as zkteco_core.py); install_zkteco_sync()
# must be called explicitly, same as every other install_vX(globals()).
#
# ---------------------------------------------------------------------------
# Deduplication strategy (closes the item Phase 1 left open):
#   ZKTeco's iFace-class protocol (via pyzk) does not expose a real per-punch
#   transaction id -- see zkteco_connector.py's header comment for the
#   verified detail. So record_uid here is a SYNTHETIC key computed locally:
#
#       record_uid = sha256(device_id | zk_user_id | punch_time_iso | status | punch)
#
#   This is deliberately NOT based on MAX(punch_time) as a sync cursor (that
#   approach silently drops same-timestamp punches and breaks on clock
#   changes). Instead every fetch is treated as a full/overlapping pull, and
#   the UNIQUE index below makes re-inserting an already-seen punch a no-op.
#   A UNIQUE index on record_uid is added now (additive: CREATE UNIQUE INDEX
#   IF NOT EXISTS -- never a destructive rewrite of the Phase 1 table).
#
#   Trade-off, stated explicitly: if a device fires two genuinely distinct
#   punches for the same person in the same second with the same status/punch
#   code, they collapse to one row. Given ZKTeco hardware debounces repeat
#   scans (typically several seconds), this is judged an acceptable and safe
#   default; it can be revisited once real device behavior is observed.
#
# ---------------------------------------------------------------------------
# Matching rule: a punch's zk_user_id is looked up against
# employees.zk_user_id (exact string match) ONLY. No name-based matching
# exists anywhere in this file. Unmatched zk_user_ids are recorded in
# zk_unmatched for a human to resolve later (a future mapping-UI phase);
# they are never used to auto-create an employee.
# ---------------------------------------------------------------------------

import hashlib
import json
from datetime import datetime


def _record_uid(device_id, zk_user_id, punch_time_iso, status, punch):
    raw = f"{device_id}|{zk_user_id}|{punch_time_iso}|{status}|{punch}"
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def install_zkteco_sync(g):
    """Additive-only migration: finalizes the dedup index on the Phase 1
    zk_attendance_raw table. Safe to call every startup (IF NOT EXISTS)."""
    db = g['db']
    c = db()
    try:
        c.execute(
            'CREATE UNIQUE INDEX IF NOT EXISTS idx_zk_raw_record_uid '
            'ON zk_attendance_raw(record_uid) WHERE record_uid IS NOT NULL'
        )
        c.commit()
    finally:
        c.close()


def sync_device(g, device_id, adapter, triggered_by=None):
    """Pull attendance from `adapter` (a ZKDeviceAdapter or MockZKAdapter --
    caller decides which) for logical `device_id`, and merge into
    zk_attendance_raw idempotently.

    Returns a dict summary (also the row written to zk_sync_logs):
        {device_id, fetched, new, duplicate, unmatched, failed, status, error}

    Never raises on a bad/unreachable device -- connector errors are caught,
    logged as a failed sync_log row, and returned in the summary so callers
    (CLI, future UI) don't crash on a single device being offline.
    """
    db = g['db']
    c = db()
    started_at = datetime.now().isoformat(timespec='seconds')
    summary = {
        'device_id': device_id, 'fetched': 0, 'new': 0, 'duplicate': 0,
        'unmatched': 0, 'failed': 0, 'status': 'running', 'error': None,
    }
    try:
        try:
            punches = adapter.fetch_attendance()
        except Exception as e:
            summary['status'] = 'failed'
            summary['error'] = str(e)
            summary['failed'] = 1
            _write_sync_log(c, device_id, started_at, summary, triggered_by)
            c.commit()
            return summary

        summary['fetched'] = len(punches)

        # Build the zk_user_id -> employee map once per sync call.
        emp_rows = c.execute(
            "SELECT emp_code, zk_user_id FROM employees WHERE zk_user_id IS NOT NULL"
        ).fetchall()
        zk_to_emp = {r['zk_user_id']: r['emp_code'] for r in emp_rows}

        unmatched_seen = {}  # zk_user_id -> (first_seen, last_seen, count, name_raw)

        for p in punches:
            ts_iso = p.timestamp.isoformat(timespec='seconds') if hasattr(p.timestamp, 'isoformat') else str(p.timestamp)
            ruid = _record_uid(device_id, p.zk_user_id, ts_iso, p.status, p.punch)
            matched = p.zk_user_id in zk_to_emp
            match_status = 'matched' if matched else 'unmatched'

            cur = c.execute(
                'INSERT OR IGNORE INTO zk_attendance_raw '
                '(device_id, zk_user_id, punch_time, verify_type, punch_state, '
                ' record_uid, raw_payload, match_status, processed, created_at) '
                'VALUES (?,?,?,?,?,?,?,?,0,?)',
                (device_id, p.zk_user_id, ts_iso, p.punch, p.status,
                 ruid, json.dumps({'device_uid': p.device_uid}), match_status, started_at)
            )
            inserted = (cur.rowcount or 0) > 0
            if inserted:
                summary['new'] += 1
            else:
                summary['duplicate'] += 1

            # Only count towards zk_unmatched on a genuinely NEW raw row --
            # re-fetching an already-seen punch (inserted=False) must not
            # inflate punch_count, or re-running a sync would make an
            # unmatched user's count grow forever even though nothing new
            # actually happened.
            if not matched and inserted:
                prev = unmatched_seen.get(p.zk_user_id)
                if prev is None:
                    unmatched_seen[p.zk_user_id] = [ts_iso, ts_iso, 1]
                else:
                    prev[0] = min(prev[0], ts_iso)
                    prev[1] = max(prev[1], ts_iso)
                    prev[2] += 1

        summary['unmatched'] = sum(v[2] for v in unmatched_seen.values())

        for zk_uid, (first_seen, last_seen, count) in unmatched_seen.items():
            existing = c.execute(
                'SELECT id, punch_count, first_seen FROM zk_unmatched WHERE device_id=? AND zk_user_id=?',
                (device_id, zk_uid)
            ).fetchone()
            if existing:
                c.execute(
                    'UPDATE zk_unmatched SET last_seen=?, punch_count=punch_count+? WHERE id=?',
                    (last_seen, count, existing['id'])
                )
            else:
                c.execute(
                    'INSERT INTO zk_unmatched (device_id, zk_user_id, zk_name_raw, first_seen, '
                    'last_seen, punch_count, status) VALUES (?,?,?,?,?,?,?)',
                    (device_id, zk_uid, None, first_seen, last_seen, count, 'open')
                )

        summary['status'] = 'success'
        _write_sync_log(c, device_id, started_at, summary, triggered_by)
        c.commit()
        return summary
    except Exception as e:
        c.rollback()
        summary['status'] = 'failed'
        summary['error'] = f"unexpected: {e}"
        c2 = db()
        try:
            _write_sync_log(c2, device_id, started_at, summary, triggered_by)
            c2.commit()
        finally:
            c2.close()
        return summary
    finally:
        c.close()


def _write_sync_log(c, device_id, started_at, summary, triggered_by):
    c.execute(
        'INSERT INTO zk_sync_logs (device_id, sync_type, started_at, finished_at, status, '
        'fetched_count, new_count, duplicate_count, unmatched_count, failed_count, '
        'error_message, triggered_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (device_id, 'manual', started_at, datetime.now().isoformat(timespec='seconds'),
         summary['status'], summary['fetched'], summary['new'], summary['duplicate'],
         summary['unmatched'], summary['failed'], summary['error'], triggered_by, started_at)
    )

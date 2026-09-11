# ZKTeco Integration — Phase 4: In-app UI.
#
# Scope: expose the Phase 1-3 backend (zkteco_core / zkteco_sync /
# zkteco_connector) through the application itself, so a normal user never
# needs python/CMD. This module follows the EXACT extension pattern already
# used by v10_feature_pack.py / v11_completion.py / v12_enterprise.py /
# enterprise_completion.py / production_ops.py:
#   - wrap H.do_GET / H.do_POST (fall back to the previous version for any
#     path this module doesn't own) instead of editing server.py's big
#     if/elif dispatch chain.
#   - wrap g['page'] ("page_nav" pattern) to inject a sidebar group, instead
#     of editing page()'s hardcoded groups in server.py.
# The only server.py change needed is importing this module and calling
# install_zkteco_ui(globals()) once, after Phase 1/2 are installed.
#
# No new DB migration: zk_devices / zk_attendance_raw / zk_sync_logs /
# zk_unmatched already exist (Phase 1) and employees.zk_user_id already has
# its unique partial index (server.py's own _init_db_schema()), which is
# what actually prevents a duplicate zk_user_id link -- this module just
# surfaces IntegrityError from that index as a friendly message.
#
# Permission reuse: gated on the existing 'system.manage' permission (same
# one already used by /devices and /network) rather than inventing new
# zkteco.* permissions, which would require a role_permissions migration and
# a /roles UI change. Admin always passes via can().
#
# Sync safety: "Sync Now" NEVER talks to real hardware unless the operator
# explicitly leaves "Mock / test mode" unchecked. Default is mock=on, so a
# stray click never opens a real socket to a production terminal.

import json
import uuid
from datetime import datetime
from urllib.parse import urlparse, quote, unquote

import zkteco_connector as zkc
import zkteco_sync as zks


def install_zkteco_ui(g):
    H = g['H']
    db = g['db']
    now = g['now']
    esc = g['esc']
    can = g['can']
    audit = g['audit']
    csrf_field = g['csrf_field']
    safe_name = g['safe_name']

    # ---- small local helpers -------------------------------------------------

    def _page():
        # Always resolve the *current* page() at call time (not import time),
        # since other modules may wrap it again after this one loads.
        return g['page']

    def _flash(msg, kind='ok'):
        # No session-flash mechanism exists in this app; reuse the same
        # "encode a short status in the redirect query string" approach the
        # device test-connection flow below relies on, decoded back into a
        # banner by the page renderer itself (self-contained, no new state).
        # URL-encode (not HTML-escape) here since this goes into a query
        # string, not HTML; _banner() below HTML-escapes it on the way out.
        return '&flash=' + kind + ':' + quote(msg, safe='')

    def _banner(qs):
        if 'flash=' not in (qs or ''):
            return ''
        try:
            raw = qs.split('flash=', 1)[1].split('&', 1)[0]
            kind, msg = raw.split(':', 1)
            msg = esc(unquote(msg))
            cls = 'b-ok' if kind == 'ok' else 'b-bad'
            return f'<div class="alert" style="margin-bottom:14px"><span class="badge {cls}">{"تم" if kind=="ok" else "خطأ"}</span> {msg}</div>'
        except Exception:
            return ''

    def _employee_options(selected='', unlinked_only=True):
        c = db()
        if unlinked_only:
            rows = c.execute(
                "SELECT emp_code,name FROM employees WHERE (zk_user_id IS NULL OR zk_user_id='') "
                "AND status<>'مؤرشف' ORDER BY name"
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT emp_code,name FROM employees WHERE status<>'مؤرشف' ORDER BY name"
            ).fetchall()
        c.close()
        opts = '<option value="">— اختر موظف —</option>'
        for r in rows:
            sel = ' selected' if r['emp_code'] == selected else ''
            opts += f'<option value="{esc(r["emp_code"])}"{sel}>{esc(r["name"])} ({esc(r["emp_code"])})</option>'
        return opts

    # ---- Devices page ---------------------------------------------------------

    def zk_devices_page(self, u, qs=''):
        c = db()
        rows = c.execute('SELECT * FROM zk_devices ORDER BY created_at DESC').fetchall()
        c.close()
        trs = ''
        for r in rows:
            status_cls = {'online': 'b-ok', 'offline': 'b-bad'}.get(r['status'], 'b-gray')
            status_label = {'online': '🟢 متصل', 'offline': '🔴 غير متصل'}.get(r['status'], '⚪ غير معروف')
            active_badge = '<span class="badge b-ok">مفعّل</span>' if r['active'] else '<span class="badge b-gray">معطّل</span>'
            trs += f'''<tr>
<td>{esc(r["name"] or r["device_key"])}</td>
<td>{esc(r["ip"] or "—")}:{r["port"]}</td>
<td>{esc(r["location"] or "—")}</td>
<td><span class="badge {status_cls}">{status_label}</span></td>
<td>{esc(r["last_seen"] or "—")}</td>
<td>{esc(r["last_sync_at"] or "لم تتم بعد")}</td>
<td>{active_badge}</td>
<td style="white-space:nowrap">
<form method="post" action="/zkteco/devices/test" style="display:inline">{csrf_field(u)}<input type="hidden" name="id" value="{r['id']}"><input type="hidden" name="mock" value="1"><button class="btn gray" title="اختبار بدون جهاز حقيقي">🧪 اختبار (تجريبي)</button></form>
<form method="post" action="/zkteco/devices/test" style="display:inline">{csrf_field(u)}<input type="hidden" name="id" value="{r['id']}"><button class="btn gray" title="اتصال حقيقي بالجهاز">🔌 اختبار الاتصال</button></form>
<a class="btn gray" href="/zkteco/devices?edit={r['id']}">✏️ تعديل</a>
<form method="post" action="/zkteco/devices/toggle" style="display:inline">{csrf_field(u)}<input type="hidden" name="id" value="{r['id']}"><button class="btn warn">{"⏸ تعطيل" if r['active'] else "▶️ تفعيل"}</button></form>
<form method="post" action="/zkteco/devices/delete" style="display:inline" onsubmit="return confirm('حذف الجهاز نهائيًا؟ سجلات الحضور القديمة تبقى محفوظة.');">{csrf_field(u)}<input type="hidden" name="id" value="{r['id']}"><button class="btn bad">🗑 حذف</button></form>
</td></tr>'''

        edit_id = ''
        for part in (qs or '').split('&'):
            if part.startswith('edit='):
                edit_id = part.split('=', 1)[1]
        edit_row = None
        if edit_id:
            c = db()
            edit_row = c.execute('SELECT * FROM zk_devices WHERE id=?', (edit_id,)).fetchone()
            c.close()

        pyzk_note = '' if zkc.PYZK_AVAILABLE else (
            '<div class="alert">⚠️ مكتبة الاتصال بالجهاز (pyzk) غير مثبتة على هذا السيرفر — الأزرار العادية "اختبار الاتصال"/"مزامنة" ستفشل. '
            'استخدم "اختبار (تجريبي)" للتأكد من واجهة الإدارة، وثبّت pyzk (<code>pip install pyzk</code>) على جهاز السيرفر لتفعيل الاتصال الحقيقي.</div>'
        )

        form_title = 'تعديل جهاز' if edit_row else 'إضافة جهاز جديد'
        form_action = '/zkteco/devices/save'
        eid = f'<input type="hidden" name="id" value="{edit_row["id"]}">' if edit_row else ''
        f_name = esc(edit_row['name']) if edit_row else ''
        f_ip = esc(edit_row['ip']) if edit_row else ''
        f_port = edit_row['port'] if edit_row else 4370
        f_loc = esc(edit_row['location'] or '') if edit_row else ''
        f_pass = esc(edit_row['comm_password'] or '') if edit_row else ''
        f_timeout = edit_row['timeout_seconds'] if edit_row else 10

        body = f'''<div class="top"><div class="title"><h1>🖐 أجهزة البصمة (ZKTeco)</h1><p>إدارة أجهزة الحضور والانصراف: إضافة، تعديل، تفعيل/تعطيل، واختبار الاتصال.</p></div>
<a class="btn gray" href="/zkteco/sync">➡️ المزامنة</a></div>
{_banner(qs)}{pyzk_note}
<div class="card"><h3>{form_title}</h3>
<form method="post" action="{form_action}" class="form">{csrf_field(u)}{eid}
<div class="field"><label>اسم الجهاز</label><input name="name" value="{f_name}" placeholder="مثال: بصمة الاستقبال" required></div>
<div class="field"><label>الموقع</label><input name="location" value="{f_loc}" placeholder="مثال: مبنى الإدارة - الدور الأول"></div>
<div class="field"><label>IP</label><input name="ip" value="{f_ip}" placeholder="192.168.1.201" required></div>
<div class="field"><label>Port</label><input name="port" type="number" value="{f_port}" required></div>
<div class="field"><label>كلمة مرور الاتصال (اختياري)</label><input name="comm_password" value="{f_pass}"></div>
<div class="field"><label>Timeout (ثانية)</label><input name="timeout_seconds" type="number" value="{f_timeout}"></div>
<div class="field full actions"><button class="btn">💾 حفظ</button>{'<a class="btn gray" href="/zkteco/devices">إلغاء</a>' if edit_row else ''}</div>
</form></div>
<div class="card table-wrap" style="margin-top:16px"><table class="table"><thead><tr><th>الاسم</th><th>IP:Port</th><th>الموقع</th><th>الحالة</th><th>آخر ظهور</th><th>آخر مزامنة</th><th>مفعّل؟</th><th>إجراءات</th></tr></thead>
<tbody>{trs or '<tr><td colspan="8">لا توجد أجهزة مضافة بعد. أضف أول جهاز من النموذج بالأعلى.</td></tr>'}</tbody></table></div>'''
        self.send(_page()('أجهزة البصمة', body, u, 'zkteco-devices'))

    def zk_device_save(self, u, f):
        did = self.fval(f, 'id')
        name = self.fval(f, 'name').strip()
        ip = self.fval(f, 'ip').strip()
        loc = self.fval(f, 'location').strip()
        pw = self.fval(f, 'comm_password').strip()
        try:
            port = int(self.fval(f, 'port') or 4370)
        except ValueError:
            port = 4370
        try:
            timeout = int(self.fval(f, 'timeout_seconds') or 10)
        except ValueError:
            timeout = 10
        if not name or not ip:
            return self.redirect('/zkteco/devices?' + _flash('الاسم و IP مطلوبان.', 'err').lstrip('&'))

        c = db()
        try:
            if did:
                c.execute(
                    'UPDATE zk_devices SET name=?,location=?,ip=?,port=?,comm_password=?,timeout_seconds=?,updated_at=? WHERE id=?',
                    (name, loc, ip, port, pw, timeout, now(), did)
                )
                c.commit()
                audit(u['username'], u['role'], 'تعديل جهاز بصمة', 'zk_devices', did, f'name={name};ip={ip}:{port}')
            else:
                key = safe_name(name) or ('zk-' + uuid.uuid4().hex[:6])
                exists = c.execute('SELECT 1 FROM zk_devices WHERE device_key=?', (key,)).fetchone()
                if exists:
                    key = key + '-' + uuid.uuid4().hex[:4]
                c.execute(
                    'INSERT INTO zk_devices(device_key,name,location,ip,port,comm_password,timeout_seconds,'
                    'active,status,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,1,?,?,?,?)',
                    (key, name, loc, ip, port, pw, timeout, 'unknown', u['username'], now(), now())
                )
                c.commit()
                newid = c.execute('SELECT id FROM zk_devices WHERE device_key=?', (key,)).fetchone()['id']
                audit(u['username'], u['role'], 'إضافة جهاز بصمة', 'zk_devices', str(newid), f'name={name};ip={ip}:{port}')
        finally:
            c.close()
        self.redirect('/zkteco/devices?' + _flash('تم الحفظ بنجاح.').lstrip('&'))

    def zk_device_toggle(self, u, f):
        did = self.fval(f, 'id')
        c = db()
        row = c.execute('SELECT * FROM zk_devices WHERE id=?', (did,)).fetchone()
        if not row:
            c.close(); return self.redirect('/zkteco/devices')
        newv = 0 if row['active'] else 1
        c.execute('UPDATE zk_devices SET active=?,updated_at=? WHERE id=?', (newv, now(), did))
        c.commit(); c.close()
        audit(u['username'], u['role'], 'تفعيل/تعطيل جهاز بصمة', 'zk_devices', did, f'active={newv}')
        self.redirect('/zkteco/devices?' + _flash('تم التحديث.').lstrip('&'))

    def zk_device_delete(self, u, f):
        did = self.fval(f, 'id')
        c = db()
        row = c.execute('SELECT * FROM zk_devices WHERE id=?', (did,)).fetchone()
        if row:
            c.execute('DELETE FROM zk_devices WHERE id=?', (did,))
            c.commit()
            audit(u['username'], u['role'], 'حذف جهاز بصمة', 'zk_devices', did, f'name={row["name"]}')
        c.close()
        self.redirect('/zkteco/devices?' + _flash('تم الحذف. سجلات الحضور السابقة لهذا الجهاز محفوظة كما هي.').lstrip('&'))

    def zk_device_test(self, u, f):
        did = self.fval(f, 'id')
        mock = self.fval(f, 'mock') == '1'
        c = db()
        row = c.execute('SELECT * FROM zk_devices WHERE id=?', (did,)).fetchone()
        c.close()
        if not row:
            return self.redirect('/zkteco/devices?' + _flash('الجهاز غير موجود.', 'err').lstrip('&'))
        try:
            adapter = zkc.make_adapter(dict(row), mock=mock)
            ok, message = adapter.test_connection()
        except Exception as e:
            ok, message = False, str(e)
        status = 'online' if ok else 'offline'
        c = db()
        c.execute('UPDATE zk_devices SET status=?,last_seen=?,updated_at=? WHERE id=?', (status, now(), now(), did))
        c.commit(); c.close()
        audit(u['username'], u['role'], 'اختبار اتصال جهاز بصمة', 'zk_devices', did, f'mock={mock};ok={ok};msg={message}')
        label = 'نجح الاتصال' if ok else 'فشل الاتصال'
        self.redirect('/zkteco/devices?' + _flash(f'{label} بـ {row["name"]}: {message}', 'ok' if ok else 'err').lstrip('&'))

    # ---- Sync page --------------------------------------------------------

    def zk_sync_page(self, u, qs=''):
        c = db()
        devices = c.execute('SELECT * FROM zk_devices WHERE active=1 ORDER BY name').fetchall()
        logs = c.execute(
            'SELECT l.*, COALESCE(d.name,l.device_id) as dname FROM zk_sync_logs l '
            'LEFT JOIN zk_devices d ON d.device_key=l.device_id '
            'ORDER BY l.id DESC LIMIT 100'
        ).fetchall()
        c.close()

        dev_cards = ''
        for d in devices:
            dev_cards += f'''<div class="card" style="margin-bottom:12px">
<div class="top" style="margin-bottom:8px"><div class="title"><h3 style="margin:0">{esc(d["name"])}</h3><p style="margin:4px 0 0">{esc(d["ip"])}:{d["port"]} · آخر مزامنة: {esc(d["last_sync_at"] or "لم تتم بعد")}</p></div></div>
<form method="post" action="/zkteco/sync/run" style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">{csrf_field(u)}<input type="hidden" name="id" value="{d['id']}">
<label style="display:flex;gap:6px;align-items:center;font-size:13px;color:var(--muted)"><input type="checkbox" name="mock" value="1" checked style="width:auto"> وضع تجريبي (بدون جهاز حقيقي)</label>
<button class="btn">🔄 مزامنة الآن</button></form></div>'''

        rows_html = ''
        for l in logs:
            st_cls = {'success': 'b-ok', 'failed': 'b-bad', 'running': 'b-warn'}.get(l['status'], 'b-gray')
            rows_html += f'''<tr><td>{esc(l["dname"])}</td><td>{esc(l["started_at"])}</td><td><span class="badge {st_cls}">{esc(l["status"])}</span></td>
<td>{l["fetched_count"]}</td><td>{l["new_count"]}</td><td>{l["duplicate_count"]}</td><td>{l["unmatched_count"]}</td><td>{l["failed_count"]}</td>
<td>{esc(l["triggered_by"] or "—")}</td><td>{esc(l["error_message"] or "—")}</td></tr>'''

        body = f'''<div class="top"><div class="title"><h1>🔄 مزامنة البصمة</h1><p>سحب سجلات الحضور من الأجهزة، دمجها بدون تكرار، وربطها بالموظفين تلقائيًا.</p></div>
<a class="btn gray" href="/zkteco/devices">🖐 الأجهزة</a><a class="btn gray" href="/zkteco/unmatched">🧩 غير مرتبطين</a><a class="btn gray" href="/zkteco/attendance">📋 سجلات الحضور</a></div>
{_banner(qs)}
{dev_cards or '<div class="card"><div class="alert">لا يوجد جهاز مفعّل بعد. أضف جهازًا من صفحة الأجهزة أولًا.</div></div>'}
<div class="card table-wrap" style="margin-top:16px"><h3>سجل عمليات المزامنة</h3><table class="table"><thead><tr><th>الجهاز</th><th>البداية</th><th>الحالة</th><th>مجلوب</th><th>جديد</th><th>مكرر</th><th>غير مرتبط</th><th>فشل</th><th>بواسطة</th><th>خطأ</th></tr></thead>
<tbody>{rows_html or '<tr><td colspan="10">لا توجد عمليات مزامنة بعد.</td></tr>'}</tbody></table></div>'''
        self.send(_page()('مزامنة البصمة', body, u, 'zkteco-sync'))

    def zk_sync_run(self, u, f):
        did = self.fval(f, 'id')
        mock = self.fval(f, 'mock') == '1'
        c = db()
        row = c.execute('SELECT * FROM zk_devices WHERE id=?', (did,)).fetchone()
        c.close()
        if not row:
            return self.redirect('/zkteco/sync?' + _flash('الجهاز غير موجود.', 'err').lstrip('&'))
        try:
            adapter = zkc.make_adapter(dict(row), mock=mock)
        except Exception as e:
            return self.redirect('/zkteco/sync?' + _flash(f'تعذر تجهيز الاتصال: {e}', 'err').lstrip('&'))

        summary = zks.sync_device(g, row['device_key'], adapter, triggered_by=u['username'])

        c = db()
        c.execute(
            'UPDATE zk_devices SET last_sync_at=?,status=?,updated_at=? WHERE id=?',
            (now(), 'online' if summary['status'] == 'success' else 'offline', now(), did)
        )
        c.commit(); c.close()
        audit(u['username'], u['role'], 'تشغيل مزامنة بصمة', 'zk_devices', did,
              f'status={summary["status"]};new={summary["new"]};dup={summary["duplicate"]};unmatched={summary["unmatched"]};failed={summary["failed"]}')

        if summary['status'] == 'success':
            msg = f'تمت المزامنة: {summary["fetched"]} سجل مجلوب، {summary["new"]} جديد، {summary["duplicate"]} مكرر، {summary["unmatched"]} غير مرتبط.'
            self.redirect('/zkteco/sync?' + _flash(msg).lstrip('&'))
        else:
            self.redirect('/zkteco/sync?' + _flash(f'فشلت المزامنة: {summary["error"] or "خطأ غير معروف"}', 'err').lstrip('&'))

    # ---- Unmatched employees page ------------------------------------------

    def zk_unmatched_page(self, u, qs=''):
        c = db()
        rows = c.execute(
            'SELECT m.*, COALESCE(d.name,m.device_id) as dname FROM zk_unmatched m '
            'LEFT JOIN zk_devices d ON d.device_key=m.device_id '
            "WHERE m.status='open' ORDER BY m.last_seen DESC LIMIT 300"
        ).fetchall()
        c.close()
        trs = ''
        for r in rows:
            trs += f'''<tr><td>{esc(r["dname"])}</td><td><b>{esc(r["zk_user_id"])}</b></td><td>{esc(r["zk_name_raw"] or "—")}</td>
<td>{r["punch_count"]}</td><td>{esc(r["first_seen"])}</td><td>{esc(r["last_seen"])}</td>
<td><form method="post" action="/zkteco/unmatched/resolve" style="display:flex;gap:6px;align-items:center">{csrf_field(u)}<input type="hidden" name="id" value="{r['id']}">
<select name="emp_code" required>{_employee_options()}</select>
<button class="btn ok">🔗 ربط</button></form></td></tr>'''
        body = f'''<div class="top"><div class="title"><h1>🧩 الموظفون غير المرتبطين بالبصمة</h1><p>مستخدمو أجهزة ZKTeco الذين ظهرت بصماتهم ولا يوجد لهم موظف مرتبط بعد. الربط هنا يدوي وآمن — لا يوجد ربط تلقائي أبدًا.</p></div>
<a class="btn gray" href="/zkteco/sync">🔄 المزامنة</a></div>
{_banner(qs)}
<div class="card table-wrap"><table class="table"><thead><tr><th>الجهاز</th><th>ZK User ID</th><th>الاسم على الجهاز</th><th>عدد البصمات</th><th>أول ظهور</th><th>آخر ظهور</th><th>ربط بموظف</th></tr></thead>
<tbody>{trs or '<tr><td colspan="7">لا يوجد مستخدمون غير مرتبطين حاليًا. 👍</td></tr>'}</tbody></table></div>'''
        self.send(_page()('غير مرتبطين', body, u, 'zkteco-unmatched'))

    def zk_unmatched_resolve(self, u, f):
        mid = self.fval(f, 'id')
        emp_code = self.fval(f, 'emp_code').strip()
        if not mid or not emp_code:
            return self.redirect('/zkteco/unmatched?' + _flash('اختر موظفًا أولًا.', 'err').lstrip('&'))
        c = db()
        m = c.execute('SELECT * FROM zk_unmatched WHERE id=?', (mid,)).fetchone()
        emp = c.execute('SELECT * FROM employees WHERE emp_code=?', (emp_code,)).fetchone()
        if not m or not emp:
            c.close()
            return self.redirect('/zkteco/unmatched?' + _flash('السجل أو الموظف غير موجود.', 'err').lstrip('&'))
        if emp['zk_user_id']:
            c.close()
            return self.redirect('/zkteco/unmatched?' + _flash('هذا الموظف مرتبط بالفعل بمستخدم بصمة آخر.', 'err').lstrip('&'))
        try:
            c.execute('UPDATE employees SET zk_user_id=? WHERE emp_code=?', (m['zk_user_id'], emp_code))
            c.execute(
                "UPDATE zk_unmatched SET status='resolved',resolved_emp_code=?,resolved_by=?,resolved_at=? WHERE id=?",
                (emp_code, u['username'], now(), mid)
            )
            # Existing raw punches for this zk_user_id are now matched too.
            c.execute(
                "UPDATE zk_attendance_raw SET match_status='matched' WHERE zk_user_id=? AND match_status<>'matched'",
                (m['zk_user_id'],)
            )
            c.commit()
        except Exception as e:
            c.rollback(); c.close()
            # The partial UNIQUE index on employees.zk_user_id is the real
            # guarantee against duplicates; surface it as a friendly message
            # instead of a raw IntegrityError.
            return self.redirect('/zkteco/unmatched?' + _flash(f'تعذّر الربط (رقم البصمة مستخدم بالفعل؟): {e}', 'err').lstrip('&'))
        c.close()
        audit(u['username'], u['role'], 'ربط موظف ببصمة', 'employees', emp_code, f'zk_user_id={m["zk_user_id"]}')
        self.redirect('/zkteco/unmatched?' + _flash(f'تم ربط {emp["name"]} برقم البصمة {m["zk_user_id"]}.').lstrip('&'))

    # ---- Attendance (raw punches) page -------------------------------------

    def zk_attendance_page(self, u, qs=''):
        params = {}
        for part in (qs or '').split('&'):
            if '=' in part:
                k, v = part.split('=', 1)
                params[k] = v
        from urllib.parse import unquote_plus
        f_device = unquote_plus(params.get('device', ''))
        f_status = unquote_plus(params.get('status', ''))
        f_q = unquote_plus(params.get('q', ''))
        f_from = unquote_plus(params.get('from', ''))
        f_to = unquote_plus(params.get('to', ''))

        where = ['1=1']
        args = []
        if f_device:
            where.append('r.device_id=?'); args.append(f_device)
        if f_status in ('matched', 'unmatched'):
            where.append('r.match_status=?'); args.append(f_status)
        if f_from:
            where.append('r.punch_time>=?'); args.append(f_from)
        if f_to:
            where.append('r.punch_time<=?'); args.append(f_to + 'T23:59:59')
        if f_q:
            where.append('(r.zk_user_id LIKE ? OR e.name LIKE ? OR e.emp_code LIKE ?)')
            like = '%' + f_q + '%'
            args += [like, like, like]

        c = db()
        devices = c.execute('SELECT device_key,name FROM zk_devices ORDER BY name').fetchall()
        rows = c.execute(
            f'''SELECT r.*, COALESCE(d.name,r.device_id) as dname, e.name as emp_name, e.emp_code as emp_code
                FROM zk_attendance_raw r
                LEFT JOIN zk_devices d ON d.device_key=r.device_id
                LEFT JOIN employees e ON e.zk_user_id=r.zk_user_id
                WHERE {" AND ".join(where)}
                ORDER BY r.punch_time DESC LIMIT 300''',
            args
        ).fetchall()
        c.close()

        dev_opts = '<option value="">كل الأجهزة</option>' + ''.join(
            f'<option value="{esc(d["device_key"])}"{" selected" if d["device_key"]==f_device else ""}>{esc(d["name"])}</option>'
            for d in devices
        )
        st_opts = ''.join(
            f'<option value="{v}"{" selected" if v==f_status else ""}>{lbl}</option>'
            for v, lbl in (('', 'كل الحالات'), ('matched', 'مرتبط'), ('unmatched', 'غير مرتبط'))
        )

        trs = ''
        for r in rows:
            badge = '<span class="badge b-ok">مرتبط</span>' if r['match_status'] == 'matched' else '<span class="badge b-warn">غير مرتبط</span>'
            who = f'{esc(r["emp_name"])} ({esc(r["emp_code"])})' if r['emp_name'] else f'زمن {esc(r["zk_user_id"])} — بلا ربط'
            trs += f'<tr><td>{esc(r["dname"])}</td><td>{who}</td><td>{esc(r["zk_user_id"])}</td><td>{esc(r["punch_time"])}</td><td>{badge}</td></tr>'

        body = f'''<div class="top"><div class="title"><h1>📋 سجلات حضور البصمة</h1><p>آخر 300 بصمة مستوردة من كل الأجهزة، بحالة الربط بالموظف.</p></div>
<a class="btn gray" href="/zkteco/unmatched">🧩 مراجعة غير المرتبطين</a></div>
<form method="get" action="/zkteco/attendance" class="toolbar">
<select name="device">{dev_opts}</select>
<select name="status">{st_opts}</select>
<input type="text" name="q" value="{esc(f_q)}" placeholder="بحث: اسم موظف، كود، أو ZK User ID">
<input type="date" name="from" value="{esc(f_from)}">
<input type="date" name="to" value="{esc(f_to)}">
<button class="btn">🔍 بحث</button>
<a class="btn gray" href="/zkteco/attendance">مسح الفلاتر</a>
</form>
<div class="card table-wrap"><table class="table"><thead><tr><th>الجهاز</th><th>الموظف</th><th>ZK User ID</th><th>وقت البصمة</th><th>الحالة</th></tr></thead>
<tbody>{trs or '<tr><td colspan="5">لا توجد سجلات مطابقة لهذه الفلاتر.</td></tr>'}</tbody></table></div>'''
        self.send(_page()('سجلات الحضور - البصمة', body, u, 'zkteco-attendance'))

    # ---- Wire routes (wrap do_GET / do_POST, same pattern as v10-v12) -----

    old_get = H.do_GET
    old_post = H.do_POST

    def get(self):
        p = urlparse(self.path).path
        full = self.path
        qs = full.split('?', 1)[1] if '?' in full else ''
        if p == '/zkteco/devices':
            u = self.require()
            if not u: return None
            return self.need(u, 'system.manage') and zk_devices_page(self, u, qs)
        if p == '/zkteco/sync':
            u = self.require()
            if not u: return None
            return self.need(u, 'system.manage') and zk_sync_page(self, u, qs)
        if p == '/zkteco/unmatched':
            u = self.require()
            if not u: return None
            return self.need(u, 'system.manage') and zk_unmatched_page(self, u, qs)
        if p == '/zkteco/attendance':
            u = self.require()
            if not u: return None
            return self.need(u, 'system.manage') and zk_attendance_page(self, u, qs)
        return old_get(self)

    def post(self):
        p = urlparse(self.path).path
        zk_paths = (
            '/zkteco/devices/save', '/zkteco/devices/toggle', '/zkteco/devices/delete',
            '/zkteco/devices/test', '/zkteco/sync/run', '/zkteco/unmatched/resolve',
        )
        if p not in zk_paths:
            return old_post(self)
        u = self.require()
        if not u: return None
        if u.get('must_change_password'):
            return self.redirect('/password')
        ctype = self.headers.get('Content-Type', '').lower()
        f = self.form() if not ctype.startswith('multipart/form-data') else self.parse_upload()[0]
        if f.get('_csrf') != u.get('csrf'):
            return self.send(_page()('خطأ أمني', '<div class="card"><div class="alert">انتهت صلاحية النموذج. أعد تحميل الصفحة وحاول مرة أخرى.</div></div>', u), 403)
        if not self.need(u, 'system.manage'):
            return None
        if p == '/zkteco/devices/save': return zk_device_save(self, u, f)
        if p == '/zkteco/devices/toggle': return zk_device_toggle(self, u, f)
        if p == '/zkteco/devices/delete': return zk_device_delete(self, u, f)
        if p == '/zkteco/devices/test': return zk_device_test(self, u, f)
        if p == '/zkteco/sync/run': return zk_sync_run(self, u, f)
        if p == '/zkteco/unmatched/resolve': return zk_unmatched_resolve(self, u, f)

    H.do_GET = get
    H.do_POST = post

    # ---- Sidebar (page_nav pattern, same as v12_enterprise.py) ------------

    old_page = g['page']

    def zk_page_nav(title, body, user, active='dashboard'):
        out = old_page(title, body, user, active)
        if user and can(user, 'system.manage'):
            keys = ('zkteco-devices', 'zkteco-sync', 'zkteco-unmatched', 'zkteco-attendance')
            items = (
                ('zkteco-devices', '🖐 أجهزة البصمة', '/zkteco/devices'),
                ('zkteco-sync', '🔄 مزامنة البصمة', '/zkteco/sync'),
                ('zkteco-unmatched', '🧩 غير مرتبطين (بصمة)', '/zkteco/unmatched'),
                ('zkteco-attendance', '📋 سجلات حضور البصمة', '/zkteco/attendance'),
            )
            inner = ''.join(
                f'<a class="{"active" if active==k else ""}" href="{href}">{label}</a>'
                for k, label, href in items
            )
            opened = 'open' if active in keys else ''
            extra = f'<details class="nav-group" {opened}><summary>🖐 البصمة (ZKTeco)</summary>{inner}</details>'
            out = out.replace('</nav>', extra + '</nav>', 1)
        return out

    g['page'] = zk_page_nav

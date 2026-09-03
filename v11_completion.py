"""HR Enterprise V11 completion layer.
Keeps the stable V10 application and adds practical feature-completion endpoints.
No framework migration and no microservices: one app, clear business features.
"""
import os, json, time, socket, secrets, hashlib, sqlite3, threading, urllib.parse


def install_v11(g):
    H=g['H']; db=g['db']; now=g['now']; esc=g['esc']; page=g['page']; csrf_field=g['csrf_field']; can=g['can']; audit=g['audit']; setting=g['setting']; DATA=g['DATA']; PORT=g['PORT']; DISCOVERY_PORT=g.get('DISCOVERY_PORT',8898)

    def ensure_schema():
        c=db();
        stmts=[
        "CREATE TABLE IF NOT EXISTS saved_views_v11(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,user_name TEXT,entity TEXT,filters_json TEXT,created_at TEXT,updated_at TEXT)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_saved_views_v11_user_name ON saved_views_v11(user_name,name,entity)",
        "CREATE TABLE IF NOT EXISTS workflow_transitions(id INTEGER PRIMARY KEY AUTOINCREMENT,request_id INTEGER,from_status TEXT,to_status TEXT,actor TEXT,comment TEXT,created_at TEXT)",
        "CREATE TABLE IF NOT EXISTS notification_actions(id INTEGER PRIMARY KEY AUTOINCREMENT,notification_id INTEGER,action TEXT,actor TEXT,created_at TEXT)",
        "CREATE TABLE IF NOT EXISTS device_admin_events(id INTEGER PRIMARY KEY AUTOINCREMENT,device_id TEXT,action TEXT,actor TEXT,created_at TEXT,details TEXT)",
        "CREATE TABLE IF NOT EXISTS mapping_templates_v11(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,user_name TEXT,company_key TEXT,signature TEXT,mapping_json TEXT,confidence REAL,version INTEGER DEFAULT 1,created_at TEXT,updated_at TEXT)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_mapping_v11 ON mapping_templates_v11(name,user_name,company_key)",
        "CREATE TABLE IF NOT EXISTS intelligence_actions(id INTEGER PRIMARY KEY AUTOINCREMENT,alert_key TEXT,action TEXT,actor TEXT,created_at TEXT,details TEXT)",
        "CREATE TABLE IF NOT EXISTS security_login_events(id INTEGER PRIMARY KEY AUTOINCREMENT,user_name TEXT,ip TEXT,event TEXT,created_at TEXT,details TEXT)",
        "CREATE TABLE IF NOT EXISTS sync_queue_v11(id INTEGER PRIMARY KEY AUTOINCREMENT,user_name TEXT,operation TEXT,payload_json TEXT,status TEXT DEFAULT 'queued',created_at TEXT,processed_at TEXT,error TEXT)",
        ]
        for s in stmts: c.execute(s)
        c.commit(); c.close()
    ensure_schema()

    def post_csrf(self,u):
        return u and u.get('csrf') == H.form(self).get('_csrf')

    def v11_excel(self,u):
        if not u or not can(u,'employees.edit'): return
        headers=['Employee Code','Name','National ID','Department','Unit','Job','Email','Phone','Contract Date']
        hjson=json.dumps(headers,ensure_ascii=False)
        body=r'''<div class="top"><div class="title"><h1>📊 Excel Grid</h1><p>Range selection, drag, keyboard navigation, clipboard, fill, undo/redo and column resize.</p></div></div>
        <div class="card"><div class="actions"><button class="btn" id="copy">Copy</button><button class="btn gray" id="cut">Cut</button><button class="btn" id="paste">Paste</button><button class="btn gray" id="undo">Undo</button><button class="btn gray" id="redo">Redo</button><button class="btn" id="down">Fill Down</button><button class="btn" id="right">Fill Right</button><button class="btn" id="ar">Add Row</button><button class="btn bad" id="dr">Delete Row</button><button class="btn" id="ac">Add Column</button><button class="btn bad" id="dc">Delete Column</button><span id="status" style="margin-left:10px"></span></div></div>
        <div class="card" style="overflow:auto;margin-top:12px"><table id="grid" class="table" style="min-width:1100px;user-select:none"><thead><tr id="head"></tr></thead><tbody id="body"></tbody></table></div>
        <style>#grid th{position:relative;min-width:130px}#grid th .grip{position:absolute;right:0;top:0;width:6px;height:100%;cursor:col-resize}#grid td.sel{outline:2px solid #175cd3;background:#eaf2ff}.cell-err{background:#ffe8e8!important}.cell-warn{background:#fff6d6!important}.cell-ok{background:#e9f9ef!important}</style>
        <script>
        const HEADERS=__HJSON__; let data=[HEADERS.slice(),Array(HEADERS.length).fill('')],anchor=null,dragging=false,undo=[],redo=[];
        const $=x=>document.getElementById(x), snap=()=>JSON.stringify(data); function pushUndo(){undo.push(snap());if(undo.length>100)undo.shift();redo=[]};
        function render(){const h=$('head'),b=$('body');h.innerHTML='';HEADERS.forEach((x,i)=>{let th=document.createElement('th');th.textContent=x;let grip=document.createElement('span');grip.className='grip';grip.onmousedown=e=>resizeStart(e,i);th.appendChild(grip);h.appendChild(th)});b.innerHTML='';for(let r=1;r<data.length;r++){let tr=document.createElement('tr');tr.dataset.r=r;for(let c=0;c<HEADERS.length;c++){let td=document.createElement('td');td.contentEditable='true';td.dataset.r=r;td.dataset.c=c;td.textContent=data[r][c]||'';td.oninput=()=>{data[r][c]=td.textContent;validate(td,c)};td.onmousedown=e=>{if(e.shiftKey&&anchor){select(anchor,{r,c})}else{anchor={r,c};clearSel();td.classList.add('sel')}dragging=true};td.onmouseover=()=>{if(dragging&&anchor)select(anchor,{r,c})};td.onkeydown=e=>key(e,r,c);validate(td,c);tr.appendChild(td)}b.appendChild(tr)}}
        document.onmouseup=()=>dragging=false;function clearSel(){document.querySelectorAll('#grid td.sel').forEach(x=>x.classList.remove('sel'))}function select(a,z){clearSel();let r1=Math.min(a.r,z.r),r2=Math.max(a.r,z.r),c1=Math.min(a.c,z.c),c2=Math.max(a.c,z.c);for(let r=r1;r<=r2;r++)for(let c=c1;c<=c2;c++)document.querySelector(`#grid td[data-r="${r}"][data-c="${c}"]`)?.classList.add('sel')}
        function key(e,r,c){if(e.key==='Tab'||e.key==='Enter'){e.preventDefault();let nr=r+(e.key==='Enter'?1:0),nc=c+(e.key==='Tab'?1:0);if(nc>=HEADERS.length){nc=0;nr++}if(nr>=data.length)data.push(Array(HEADERS.length).fill(''));render();document.querySelector(`#grid td[data-r="${nr}"][data-c="${nc}"]`)?.focus()}else if(e.key==='ArrowDown'||e.key==='ArrowUp'||e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();let nr=r+(e.key==='ArrowDown'?1:e.key==='ArrowUp'?-1:0),nc=c+(e.key==='ArrowRight'?1:e.key==='ArrowLeft'?-1:0);nr=Math.max(1,Math.min(data.length-1,nr));nc=Math.max(0,Math.min(HEADERS.length-1,nc));if(e.shiftKey)select(anchor||{r,c},{r:nr,c:nc});document.querySelector(`#grid td[data-r="${nr}"][data-c="${nc}"]`)?.focus()}else if((e.ctrlKey||e.metaKey)&&['z','y','c','x','v'].includes(e.key.toLowerCase())){e.preventDefault();let k=e.key.toLowerCase();if(k==='z'){if(undo.length){redo.push(snap());data=JSON.parse(undo.pop());render()}}else if(k==='y'){if(redo.length){undo.push(snap());data=JSON.parse(redo.pop());render()}}else if(k==='c'||k==='x')copyCells(k==='x')}}
        function selectedCells(){return [...document.querySelectorAll('#grid td.sel')].sort((a,b)=>a.dataset.r-b.dataset.r||a.dataset.c-b.dataset.c)}function copyCells(cut){let cells=selectedCells();if(!cells.length)return;let rs=[...new Set(cells.map(x=>+x.dataset.r))].sort((a,b)=>a-b),cs=[...new Set(cells.map(x=>+x.dataset.c))].sort((a,b)=>a-b);let text=rs.map(r=>cs.map(c=>data[r][c]||'').join('\t')).join('\n');navigator.clipboard?.writeText(text);if(cut){pushUndo();cells.forEach(x=>data[+x.dataset.r][+x.dataset.c]='');render()}$('status').textContent='Copied '+cells.length+' cells'}
        async function pasteText(){try{let t=await navigator.clipboard.readText();let rows=t.replace(/\r/g,'').split('\n').filter(Boolean).map(x=>x.split('\t'));let cells=selectedCells();let start=cells[0]||document.querySelector('#grid td');if(!start)return;pushUndo();let r0=+start.dataset.r,c0=+start.dataset.c;rows.forEach((row,dr)=>row.forEach((v,dc)=>{while(!data[r0+dr])data.push(Array(HEADERS.length).fill(''));if(c0+dc>=HEADERS.length)return;data[r0+dr][c0+dc]=v}));render();$('status').textContent='Pasted '+rows.length+' rows'}catch(e){alert('Clipboard access denied. Use Ctrl+V in a cell.')}}
        function fill(dir){let cells=selectedCells();if(!cells.length)return;let rs=cells.map(x=>+x.dataset.r),cs=cells.map(x=>+x.dataset.c),r1=Math.min(...rs),r2=Math.max(...rs),c1=Math.min(...cs),c2=Math.max(...cs);pushUndo();if(dir==='down')for(let r=r1+1;r<=r2;r++)for(let c=c1;c<=c2;c++)data[r][c]=data[r1][c];else for(let c=c1+1;c<=c2;c++)for(let r=r1;r<=r2;r++)data[r][c]=data[r][c1];render()}
        $('copy').onclick=()=>copyCells(false);$('cut').onclick=()=>copyCells(true);$('paste').onclick=pasteText;$('undo').onclick=()=>{if(undo.length){redo.push(snap());data=JSON.parse(undo.pop());render()}};$('redo').onclick=()=>{if(redo.length){undo.push(snap());data=JSON.parse(redo.pop());render()}};$('down').onclick=()=>fill('down');$('right').onclick=()=>fill('right');$('ar').onclick=()=>{pushUndo();data.push(Array(HEADERS.length).fill(''));render()};$('dr').onclick=()=>{let cells=selectedCells();if(!cells.length)return;let r=Math.max(...cells.map(x=>+x.dataset.r));pushUndo();data.splice(r,1);render()};$('ac').onclick=()=>{pushUndo();HEADERS.push('New Column');data.forEach(r=>r.push(''));render()};$('dc').onclick=()=>{let cells=selectedCells();if(!cells.length)return;let c=+cells[0].dataset.c;pushUndo();HEADERS.splice(c,1);data.forEach(r=>r.splice(c,1));render()};function validate(td,c){let v=td.textContent.trim(),h=HEADERS[c];td.classList.remove('cell-err','cell-warn','cell-ok');if(!v&&['Employee Code','Name'].includes(h))td.classList.add('cell-err');else if(h==='Email'&&v&&!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v))td.classList.add('cell-err');else if(v)td.classList.add('cell-ok')}function resizeStart(e,i){e.preventDefault();let th=e.target.parentElement,start=e.clientX,w=th.offsetWidth;let move=x=>th.style.width=Math.max(80,w+x.clientX-start)+'px';let up=()=>{document.removeEventListener('mousemove',move);document.removeEventListener('mouseup',up)};document.addEventListener('mousemove',move);document.addEventListener('mouseup',up)}render();
        </script>'''.replace('__HJSON__',hjson)
        self.send(page('Excel Grid',body,u,'import'))

    def mapping(self,u):
        if not can(u,'employees.edit'): return
        c=db(); rows=c.execute('SELECT * FROM mapping_templates_v11 WHERE user_name=? ORDER BY updated_at DESC',(u['username'],)).fetchall(); c.close()
        trs=''.join(f'<tr><td>{esc(r["name"])}</td><td>{esc(r["company_key"])}</td><td>{float(r["confidence"] or 0)*100:.0f}%</td><td>v{r["version"]}</td><td>{esc(r["updated_at"])}</td></tr>' for r in rows)
        body=f'''<div class="top"><div class="title"><h1>🧠 Smart Import Mapping</h1><p>Save a mapping once and reuse it on the next import.</p></div></div><div class="card"><form method="post" action="/v11/mapping/save">{csrf_field(u)}<div class="form"><div class="field"><label>Template</label><input name="name" required></div><div class="field"><label>Company</label><input name="company" value="default"></div><div class="field full"><label>Mapping JSON</label><textarea name="mapping" rows="6" placeholder='{{"Name":"Employee Name","Department":"Department"}}' required></textarea></div><div class="field"><label>Confidence %</label><input name="confidence" type="number" min="0" max="100" value="100"></div></div><button class="btn">Save Mapping</button></form></div><div class="card" style="margin-top:12px"><h3>Saved mappings</h3><table class="table"><tr><th>Name</th><th>Company</th><th>Confidence</th><th>Version</th><th>Updated</th></tr>{trs or '<tr><td colspan=5>No mappings yet</td></tr>'}</table></div>'''
        self.send(page('Smart Mapping',body,u,'import'))

    def mapping_save(self,u,f):
        if not can(u,'employees.edit'): return
        try: mp=json.loads(f.get('mapping','{}'))
        except Exception: return self.send(page('Mapping','<div class="card"><div class="alert">Invalid mapping JSON.</div></div>',u),400)
        name=f.get('name','').strip(); company=f.get('company','default').strip() or 'default'; conf=max(0,min(100,float(f.get('confidence','100'))))/100
        sig=hashlib.sha256(json.dumps(mp,sort_keys=True,ensure_ascii=False).encode()).hexdigest(); c=db(); old=c.execute('SELECT version FROM mapping_templates_v11 WHERE name=? AND user_name=? AND company_key=?',(name,u['username'],company)).fetchone(); ver=(old['version']+1) if old else 1
        c.execute('INSERT INTO mapping_templates_v11(name,user_name,company_key,signature,mapping_json,confidence,version,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(name,user_name,company_key) DO UPDATE SET signature=excluded.signature,mapping_json=excluded.mapping_json,confidence=excluded.confidence,version=excluded.version,updated_at=excluded.updated_at',(name,u['username'],company,sig,json.dumps(mp,ensure_ascii=False),conf,ver,now(),now())); c.commit(); c.close(); audit(u['username'],u['role'],'Save import mapping','Imports',name,f'confidence={conf}'); self.redirect('/v11/mapping')

    def intelligence(self,u):
        if not can(u,'employees.view'): return
        c=db(); rows=c.execute("SELECT id,title,message,created_at,read_at FROM notifications WHERE user_name=? ORDER BY id DESC LIMIT 100",(u['username'],)).fetchall(); c.close()
        body='<div class="top"><div class="title"><h1>🚨 Intelligence & Notifications</h1><p>Review alerts and act on them.</p></div></div><div class="card"><table class="table"><tr><th>Time</th><th>Alert</th><th>Message</th><th>Status</th><th>Action</th></tr>'+''.join(f'<tr><td>{esc(r["created_at"])}</td><td>{esc(r["title"])}</td><td>{esc(r["message"])}</td><td>{"Read" if r["read_at"] else "Unread"}</td><td><form method="post" action="/v11/notification/action">{csrf_field(u)}<input type="hidden" name="id" value="{r["id"]}"><button class="btn gray" name="action" value="read">Read</button><button class="btn" name="action" value="snooze">Snooze</button></form></td></tr>' for r in rows)+'</table></div>'
        self.send(page('Intelligence',body,u,'notifications'))

    def notification_action(self,u,f):
        nid=int(f.get('id','0') or 0); action=f.get('action','read'); c=db();
        if action=='read': c.execute('UPDATE notifications SET read_at=? WHERE id=? AND user_name=?',(now(),nid,u['username']))
        c.execute('INSERT INTO notification_actions(notification_id,action,actor,created_at) VALUES(?,?,?,?)',(nid,action,u['username'],now())); c.commit(); c.close(); audit(u['username'],u['role'],'Notification action','Notifications',str(nid),action); self.redirect('/v11/intelligence')

    def devices(self,u):
        if not can(u,'system.manage'): return
        c=db(); rows=c.execute('SELECT d.*,COALESCE(t.approved,0) approved,COALESCE(t.revoked,0) revoked FROM device_registry d LEFT JOIN device_trust t ON t.device_id=d.device_id ORDER BY d.last_seen DESC').fetchall(); c.close()
        trs=''
        for r in rows:
            try: online=(time.time()-time.mktime(time.strptime(r['last_seen'],'%Y-%m-%d %H:%M:%S')))<90
            except Exception: online=True
            status='Online' if online else 'Offline'; trust='Approved' if r['approved'] and not r['revoked'] else 'Review'
            trs+=f'<tr><td>{esc(r["device_name"])}</td><td>{esc(r["username"])}</td><td>{esc(r["ip"])}</td><td>{status}</td><td>{trust}</td><td><form method="post" action="/v11/device/action">{csrf_field(u)}<input type="hidden" name="id" value="{esc(r["device_id"])}"><input name="name" placeholder="Rename"><button class="btn" name="action" value="approve">Approve</button><button class="btn bad" name="action" value="revoke">Revoke</button><button class="btn gray" name="action" value="disconnect">Disconnect</button><button class="btn" name="action" value="rename">Rename</button></form></td></tr>'
        body=f'<div class="top"><div class="title"><h1>🖥 Connected Devices</h1><p>Manage approval, revoke, rename and disconnect.</p></div></div><div class="card"><table class="table"><tr><th>Device</th><th>User</th><th>IP</th><th>State</th><th>Trust</th><th>Actions</th></tr>{trs or "<tr><td colspan=6>No devices</td></tr>"}</table></div>'
        self.send(page('Devices',body,u,'devices'))

    def device_action(self,u,f):
        did=f.get('id',''); action=f.get('action',''); name=f.get('name','').strip(); c=db()
        if action in ('approve','revoke'):
            c.execute('INSERT INTO device_trust(device_id,approved,revoked,updated_at) VALUES(?,?,?,?) ON CONFLICT(device_id) DO UPDATE SET approved=excluded.approved,revoked=excluded.revoked,updated_at=excluded.updated_at',(did,1 if action=='approve' else 0,1 if action=='revoke' else 0,now()))
        elif action=='rename' and name:
            c.execute('UPDATE device_registry SET device_name=? WHERE device_id=?',(name,did))
        elif action=='disconnect':
            c.execute('INSERT INTO device_events(device_id,event_type,ts,message) VALUES(?,?,?,?)',(did,'disconnect',now(),'Disconnected by admin'))
            c.execute('UPDATE device_registry SET last_seen=? WHERE device_id=?',(now(),did))
        c.execute('INSERT INTO device_admin_events(device_id,action,actor,created_at,details) VALUES(?,?,?,?,?)',(did,action,u['username'],now(),name)); c.commit(); c.close(); audit(u['username'],u['role'],'Device action','Devices',did,action); self.redirect('/v11/devices')

    def workflow(self,u):
        if not can(u,'employees.view'): return
        c=db(); rows=c.execute('SELECT * FROM employee_requests ORDER BY id DESC LIMIT 100').fetchall(); c.close();
        body='<div class="top"><div class="title"><h1>🔄 Workflow</h1><p>Simple, correct lifecycle: Draft → Submitted → Manager → HR → Approved/Rejected.</p></div></div><div class="card"><table class="table"><tr><th>ID</th><th>Employee</th><th>Type</th><th>Status</th><th>Action</th></tr>'+''.join(f'<tr><td>{r["id"]}</td><td>{esc(r["emp_code"])}</td><td>{esc(r["request_type"])}</td><td>{esc(r["status"])}</td><td><form method="post" action="/v11/workflow/transition">{csrf_field(u)}<input type="hidden" name="id" value="{r["id"]}"><input name="comment" placeholder="Comment"><button class="btn" name="action" value="approve">Approve</button><button class="btn bad" name="action" value="reject">Reject</button><button class="btn gray" name="action" value="reopen">Reopen</button><button class="btn gray" name="action" value="cancel">Cancel</button></form></td></tr>' for r in rows)+'</table></div>'
        self.send(page('Workflow',body,u,'requests'))

    def workflow_transition(self,u,f):
        rid=int(f.get('id','0') or 0); action=f.get('action',''); comment=f.get('comment',''); c=db(); r=c.execute('SELECT * FROM employee_requests WHERE id=?',(rid,)).fetchone()
        if not r: c.close(); return self.redirect('/v11/workflow')
        old=r['status']; role=u.get('role');
        if action=='reject': new='rejected'
        elif action=='reopen': new='submitted'
        elif action=='cancel': new='cancelled'
        elif action=='approve': new='hr_approved' if role in ('Admin','HR','System Admin') else 'manager_approved'
        else: new=old
        c.execute('UPDATE employee_requests SET status=?,updated_at=? WHERE id=?',(new,now(),rid)); c.execute('INSERT INTO workflow_transitions(request_id,from_status,to_status,actor,comment,created_at) VALUES(?,?,?,?,?,?)',(rid,old,new,u['username'],comment,now())); c.execute('INSERT INTO workflow_comments(request_id,user_name,comment,created_at) VALUES(?,?,?,?)',(rid,u['username'],comment,now())); c.commit(); c.close(); audit(u['username'],u['role'],'Workflow transition','Request',str(rid),f'{old}->{new}'); self.redirect('/v11/workflow')

    def saved_views(self,u):
        c=db(); rows=c.execute('SELECT * FROM saved_views_v11 WHERE user_name=? ORDER BY id DESC',(u['username'],)).fetchall(); c.close(); trs=''.join(f'<tr><td>{esc(r["name"])}</td><td>{esc(r["entity"])}</td><td>{esc(r["filters_json"])}</td><td><form method="post" action="/v11/views/delete">{csrf_field(u)}<input type="hidden" name="id" value="{r["id"]}"><button class="btn bad">Delete</button></form></td></tr>' for r in rows)
        body=f'<div class="top"><div class="title"><h1>🔎 Saved Views</h1><p>Save useful HR filters instead of rebuilding them every time.</p></div></div><div class="card"><form method="post" action="/v11/views/save">{csrf_field(u)}<div class="form"><div class="field"><label>Name</label><input name="name" required></div><div class="field"><label>Entity</label><select name="entity"><option>employees</option><option>requests</option><option>alerts</option></select></div><div class="field full"><label>Filters JSON</label><textarea name="filters" required placeholder="{{&quot;department&quot;:&quot;Nursing&quot;,&quot;status&quot;:&quot;active&quot;}}"></textarea></div></div><button class="btn">Save View</button></form></div><div class="card" style="margin-top:12px"><table class="table"><tr><th>Name</th><th>Entity</th><th>Filters</th><th></th></tr>{trs or "<tr><td colspan=4>No saved views</td></tr>"}</table></div>'
        self.send(page('Saved Views',body,u,'employees'))
    def saved_view_save(self,u,f):
        try: json.loads(f.get('filters','{}'))
        except Exception: return self.send(page('Saved Views','<div class="card"><div class="alert">Invalid filters JSON.</div></div>',u),400)
        c=db(); c.execute('INSERT OR REPLACE INTO saved_views_v11(name,user_name,entity,filters_json,created_at,updated_at) VALUES(?,?,?,?,?,?)',(f.get('name','').strip(),u['username'],f.get('entity','employees'),f.get('filters','{}'),now(),now())); c.commit(); c.close(); self.redirect('/v11/views')
    def saved_view_delete(self,u,f):
        c=db(); c.execute('DELETE FROM saved_views_v11 WHERE id=? AND user_name=?',(f.get('id'),u['username'])); c.commit(); c.close(); self.redirect('/v11/views')

    def global_search(self,u):
        q=urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get('q',[''])[0].strip()
        c=db(); em=[]
        if q: em=c.execute("SELECT emp_code,name,department,job FROM employees WHERE emp_code LIKE ? OR name LIKE ? OR national_id LIKE ? LIMIT 30",(f'%{q}%',f'%{q}%',f'%{q}%')).fetchall()
        c.close(); body=f'<div class="top"><div class="title"><h1>⌕ Global Search</h1><p>Employees, codes and National ID.</p></div></div><div class="card"><form><input name="q" value="{esc(q)}" placeholder="Search employee..."><button class="btn">Search</button></form></div><div class="card" style="margin-top:12px"><table class="table"><tr><th>Code</th><th>Name</th><th>Department</th><th>Job</th></tr>'+''.join(f'<tr><td>{esc(r["emp_code"])}</td><td>{esc(r["name"])}</td><td>{esc(r["department"] or "")}</td><td>{esc(r["job"] or "")}</td></tr>' for r in em)+'</table></div>'
        self.send(page('Search',body,u,'employees'))

    # Route patching
    old_get, old_post = H.do_GET, H.do_POST
    H.excel_v11=v11_excel; H.mapping_v11=mapping; H.mapping_save_v11=mapping_save; H.intelligence_v11=intelligence; H.notification_action_v11=notification_action; H.devices_v11=devices; H.device_action_v11=device_action; H.workflow_v11=workflow; H.workflow_transition_v11=workflow_transition; H.saved_views_v11=saved_views; H.saved_view_save_v11=saved_view_save; H.saved_view_delete_v11=saved_view_delete; H.global_search_v11=global_search
    def get(self):
        p=urllib.parse.urlparse(self.path).path
        v11_paths=('/v11/excel','/v11/mapping','/v11/intelligence','/v11/devices','/v11/workflow','/v11/views','/v11/search')
        if p not in v11_paths:
            return old_get(self)
        u=self.require()
        if not u:return
        if p=='/v11/excel': return self.excel_v11(u)
        if p=='/v11/mapping': return self.mapping_v11(u)
        if p=='/v11/intelligence': return self.intelligence_v11(u)
        if p=='/v11/devices': return self.devices_v11(u)
        if p=='/v11/workflow': return self.workflow_v11(u)
        if p=='/v11/views': return self.saved_views_v11(u)
        if p=='/v11/search': return self.global_search_v11(u)
        return old_get(self)
    def post(self):
        p=urllib.parse.urlparse(self.path).path
        v11_paths=('/v11/mapping/save','/v11/notification/action','/v11/device/action','/v11/workflow/transition','/v11/views/save','/v11/views/delete')
        if p not in v11_paths:
            return old_post(self)
        u=self.require()
        if not u:return
        f=self.form()
        if f.get('_csrf')!=u.get('csrf'): return self.send(page('Security','<div class="card"><div class="alert">Invalid CSRF.</div></div>',u),403)
        if p=='/v11/mapping/save': return self.mapping_save_v11(u,f)
        if p=='/v11/notification/action': return self.notification_action_v11(u,f)
        if p=='/v11/device/action': return self.device_action_v11(u,f)
        if p=='/v11/workflow/transition': return self.workflow_transition_v11(u,f)
        if p=='/v11/views/save': return self.saved_view_save_v11(u,f)
        if p=='/v11/views/delete': return self.saved_view_delete_v11(u,f)
        return old_post(self)
    H.do_GET=get; H.do_POST=post

    old_page=page
    def page11(title,body,user,active='dashboard'):
        out=old_page(title,body,user,active)
        if user:
            extra='<a href="/v11/search">⌕ Search</a>'
            if can(user,'employees.edit'): extra+='<a href="/v11/excel">📊 Excel Grid</a><a href="/v11/mapping">🧠 Mapping</a>'
            if can(user,'employees.view'): extra+='<a href="/v11/intelligence">🚨 Intelligence</a><a href="/v11/workflow">🔄 Workflow</a><a href="/v11/views">🔎 Saved Views</a>'
            if can(user,'system.manage'): extra+='<a href="/v11/devices">🖥 Devices</a>'
            extra='<details class="nav-group"><summary>أدوات V11</summary>'+extra+'</details>'
            out=out.replace('</nav>',extra+'</nav>',1)
        return out
    g['page']=page11; globals()['page']=page11

import re

try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:
    psycopg = None
    dict_row = None

class PGCursor:
    def __init__(self, conn, cur):
        self._conn = conn
        self._cur = cur
        self._lastrowid = None
    @property
    def lastrowid(self):
        if self._lastrowid is not None:
            return self._lastrowid
        try:
            r = self._conn._raw.execute('SELECT lastval() AS id').fetchone()
            self._lastrowid = r['id'] if r else None
        except Exception:
            self._lastrowid = None
        return self._lastrowid
    @property
    def description(self): return self._cur.description
    @property
    def rowcount(self): return self._cur.rowcount
    def fetchone(self): return self._cur.fetchone()
    def fetchall(self): return self._cur.fetchall()
    def fetchmany(self, size=None): return self._cur.fetchmany(size) if size else self._cur.fetchmany()
    def __iter__(self): return iter(self._cur)

class PGConnection:
    def __init__(self, url):
        if psycopg is None:
            raise RuntimeError('psycopg is required for PostgreSQL mode')
        self.url = url
        self._raw = psycopg.connect(url, row_factory=dict_row, autocommit=False)
    def execute(self, sql, params=()):
        original=str(sql).strip()
        m=re.match(r'^PRAGMA\s+table_info\(([^)]+)\)\s*$', original, re.I)
        sql = translate_sql(original)
        if m:
            params=(m.group(1).strip(' \"'), m.group(1).strip(' \"'))
        cur = self._raw.cursor()
        cur.execute(sql, params or ())
        return PGCursor(self, cur)
    def executescript(self, script):
        # The project schema is deliberately simple; split statements while keeping quoted text intact.
        for stmt in split_sql(script):
            if stmt.strip(): self.execute(stmt)
        return None
    def commit(self): self._raw.commit()
    def rollback(self): self._raw.rollback()
    def close(self): self._raw.close()


def split_sql(script):
    out=[]; buf=[]; quote=None; esc=False
    for ch in script:
        if quote:
            buf.append(ch)
            if esc: esc=False
            elif ch=='\\': esc=True
            elif ch==quote: quote=None
        else:
            if ch in "'\"": quote=ch; buf.append(ch)
            elif ch==';': out.append(''.join(buf)); buf=[]
            else: buf.append(ch)
    if buf: out.append(''.join(buf))
    return out


def translate_sql(sql):
    s=str(sql).strip()
    # SQLite-only PRAGMAs. table_info is the one pragma the application actually reads.
    m=re.match(r'^PRAGMA\s+table_info\(([^)]+)\)\s*$', s, re.I)
    if m:
        table=m.group(1).strip(' "')
        return ("SELECT ordinal_position-1 AS cid, column_name AS name, data_type AS type, "
                "CASE WHEN is_nullable='NO' THEN 1 ELSE 0 END AS notnull, column_default AS dflt_value, "
                "CASE WHEN column_name IN (SELECT a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid=i.indrelid "
                "AND a.attnum=ANY(i.indkey) WHERE i.indrelid=%s::regclass AND i.indisprimary) THEN 1 ELSE 0 END AS pk "
                "FROM information_schema.columns WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position")
    if s.upper().startswith('PRAGMA '):
        return 'SELECT 1 AS ok'
    s=re.sub(r'\bCOLLATE\s+NOCASE\b','',s,flags=re.I)
    # SQLite accepts double quoted string literals; PostgreSQL treats them as identifiers.
    # The HR application uses double quotes almost exclusively for literal values in SQL.
    s=s.replace('"', "'")
    # Placeholder style.
    s=s.replace('?', '%s')
    # SQLite type aliases in CREATE TABLE statements.
    s=re.sub(r'\bBLOB\b','BYTEA',s,flags=re.I)
    s=re.sub(r'\bREAL\b','DOUBLE PRECISION',s,flags=re.I)
    s=re.sub(r'\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b','BIGSERIAL PRIMARY KEY',s,flags=re.I)
    s=re.sub(r'\bINTEGER\s+PRIMARY\s+KEY\b','BIGSERIAL PRIMARY KEY',s,flags=re.I)
    # Any other stray AUTOINCREMENT keyword (SQLite-only) has no PostgreSQL equivalent needed
    # once the column is BIGSERIAL, so drop it rather than let it fall through as a syntax error.
    s=re.sub(r'\bAUTOINCREMENT\b','',s,flags=re.I)
    # INSERT OR IGNORE -> PostgreSQL equivalent. Detect it BEFORE stripping the keyword so the
    # fix applies to every table that uses it, not a hardcoded whitelist that silently misses
    # any table added later (this previously missed alert_events, alert_rules, branding_profiles).
    was_or_ignore = bool(re.match(r'^INSERT\s+OR\s+IGNORE\s+INTO\s+', s, re.I))
    s=re.sub(r'^INSERT\s+OR\s+IGNORE\s+INTO\s+', 'INSERT INTO ', s, flags=re.I)
    if was_or_ignore and 'ON CONFLICT' not in s.upper():
        s += ' ON CONFLICT DO NOTHING'
    # INSERT OR REPLACE was used only for upsert-like attendance/saved-view operations.
    # PostgreSQL's "ON CONFLICT DO UPDATE" requires an explicit conflict target
    # (column list) -- unlike DO NOTHING, it is NOT optional. Emitting it without
    # a target is a syntax error, so the target must come from each table's real
    # UNIQUE constraint (this cannot be inferred from the INSERT text alone).
    REPLACE_CONFLICT_KEYS = {
        'attendance': ('work_date', 'emp_code'),           # UNIQUE(work_date,emp_code)
        'saved_views_v11': ('user_name', 'name', 'entity'), # ux_saved_views_v11_user_name
    }
    m=re.match(r'^INSERT\s+OR\s+REPLACE\s+INTO\s+([\w]+)\s*\(([^)]+)\)\s*(VALUES\s*\(.+\))$',str(sql).strip(),re.I|re.S)
    if m:
        table, cols, vals=m.group(1),m.group(2),m.group(3)
        col_list=[c.strip() for c in cols.split(',')]
        key=REPLACE_CONFLICT_KEYS.get(table.lower())
        if key is None:
            raise RuntimeError(
                f"pg_compat: INSERT OR REPLACE INTO {table} has no known PostgreSQL "
                f"conflict target. Add its real UNIQUE key to REPLACE_CONFLICT_KEYS "
                f"in pg_compat.py -- 'ON CONFLICT DO UPDATE' without one is invalid SQL."
            )
        set_cols=[c for c in col_list if c not in key]
        s='INSERT INTO %s (%s) %s ON CONFLICT (%s) DO UPDATE SET %s' % (
            table, cols, vals, ', '.join(key),
            ', '.join('%s=EXCLUDED.%s'%(c,c) for c in set_cols))
        s=s.replace('?', '%s').replace('"', "'")
    return s


def connect(url):
    return PGConnection(url)

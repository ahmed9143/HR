"""SQLite -> PostgreSQL migration helper. Source DB is never modified."""
import os, sqlite3
import psycopg
DB=os.environ.get('HR_SQLITE_DB','hr_central.db')
URL=os.environ.get('HR_DB_URL','postgresql://hr_admin:change-this-password@localhost:5432/hr_enterprise')
def main():
    src=sqlite3.connect(DB); src.row_factory=sqlite3.Row; dst=psycopg.connect(URL)
    try:
        tables=[r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        with dst.cursor() as cur:
            for t in tables:
                cols=src.execute(f'PRAGMA table_info("{t}")').fetchall()
                if not cols: continue
                defs=[]
                for c in cols:
                    typ=(c['type'] or 'TEXT').upper(); typ={'INTEGER':'BIGINT','REAL':'DOUBLE PRECISION','BLOB':'BYTEA'}.get(typ, 'TEXT' if typ=='NUMERIC' else typ); defs.append(f'"{c["name"]}" {typ}')
                cur.execute(f'CREATE TABLE IF NOT EXISTS "{t}" ({", ".join(defs)})')
                names=[c['name'] for c in cols]; qs=','.join(['%s']*len(names)); quoted=','.join('"'+n+'"' for n in names)
                for row in src.execute(f'SELECT * FROM "{t}"'):
                    cur.execute(f'INSERT INTO "{t}" ({quoted}) VALUES ({qs}) ON CONFLICT DO NOTHING',tuple(row[n] for n in names))
        dst.commit(); print(f'Migrated {len(tables)} tables.')
    except Exception: dst.rollback(); raise
    finally: src.close(); dst.close()
if __name__=='__main__': main()

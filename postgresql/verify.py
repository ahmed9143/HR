import os, psycopg
URL=os.environ.get('HR_DB_URL','postgresql://hr_admin:change-this-password@localhost:5432/hr_enterprise')
with psycopg.connect(URL) as c:
    with c.cursor() as cur: cur.execute('SELECT 1')
print('PostgreSQL health: PASS')

import os, sys
os.environ['HR_MODE']='network'
os.environ['HR_HOST']='0.0.0.0'
os.environ.setdefault('HR_NO_BROWSER','0')
_root=os.path.dirname(os.path.abspath(sys.executable if getattr(sys,'frozen',False) else __file__))
_pg_file=os.path.join(_root,'postgres_url.txt')
if not os.environ.get('HR_DB_URL') and os.path.exists(_pg_file):
    try: os.environ['HR_DB_URL']=open(_pg_file,encoding='utf-8-sig').read().strip()
    except Exception: pass
import server
if __name__=='__main__':
    server.main()

import os, tempfile, importlib, sqlite3

ROOT=os.path.abspath(os.path.join(os.path.dirname(__file__),'../..'))
os.environ['HR_DATA_DIR']=tempfile.mkdtemp(prefix='hr_v18_test_')
os.environ['HR_MODE']='local'
import sys
sys.path.insert(0,ROOT)
S=importlib.import_module('server')
S.init()

# Schema/policy smoke
c=S.db()
assert c.execute("SELECT 1 FROM settings WHERE key='policy_permission_normal_max_month'").fetchone()
assert c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='permission_requests'").fetchone()
assert S.APP_VERSION == '18.0.0'
c.close()
print('V18 PRODUCTION TEST: PASS')

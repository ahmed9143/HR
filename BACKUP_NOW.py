#!/usr/bin/env python3
"""Create and verify a production HR Enterprise backup from the local database."""
import os,sys
BASE=os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0,BASE)
import server
server.init()
path=server.make_backup({'username':'system','role':'SuperAdmin'},'manual_cli')
print(path)
ok,msg=server.verify_backup_package(path)
print('VERIFIED:',ok,msg)
sys.exit(0 if ok else 1)

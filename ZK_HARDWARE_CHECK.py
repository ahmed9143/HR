#!/usr/bin/env python3
"""Real-terminal diagnostic. Usage: python ZK_HARDWARE_CHECK.py 192.168.1.201 [port] [password]"""
import sys,time
from zkteco_connector import ZKDeviceAdapter,ZKConnectorError,PYZK_AVAILABLE
if len(sys.argv)<2:
    print('Usage: python ZK_HARDWARE_CHECK.py DEVICE_IP [PORT] [PASSWORD]'); sys.exit(2)
if not PYZK_AVAILABLE:
    print('FAIL: pyzk is not installed. Run: pip install -r requirements.txt'); sys.exit(1)
ip=sys.argv[1]; port=int(sys.argv[2]) if len(sys.argv)>2 else 4370; password=int(sys.argv[3]) if len(sys.argv)>3 else 0
print(f'Testing ZKTeco {ip}:{port} ...')
try:
    a=ZKDeviceAdapter(ip,port=port,password=password,timeout=10,connect_timeout=3,retries=1)
    t=time.time(); ok,msg=a.test_connection(); print('CONNECT:',ok,msg,'latency_ms=',round((time.time()-t)*1000))
    if not ok: sys.exit(1)
    rec=a.fetch_attendance(); print('ATTENDANCE READ: OK records=',len(rec)); a.disconnect(); sys.exit(0)
except ZKConnectorError as e:
    print('FAIL:',e); sys.exit(1)
except Exception as e:
    print('FAIL:',type(e).__name__,e); sys.exit(1)

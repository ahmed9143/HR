import os,sys,time,webbrowser,subprocess
from pathlib import Path
BASE=Path(__file__).resolve().parent
os.environ.setdefault("HR_MODE","auto")
os.environ.setdefault("HR_HOST","0.0.0.0")
os.environ.setdefault("HR_NO_BROWSER","0")
print("==============================================")
print(" HR Enterprise")
print(" Checking installation / database / network...")
print("==============================================")
server=BASE/"server.py"
if not server.exists():
    print("server.py not found:",server); input("Press Enter..."); raise SystemExit(1)
print("Starting HR Enterprise...")
subprocess.call([sys.executable,str(server)])

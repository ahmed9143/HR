import os, sys, winreg
from pathlib import Path
APP='HR Enterprise'
EXE=Path(sys.executable).resolve()
KEY=r'Software\Microsoft\Windows\CurrentVersion\Run'
def enable():
    k=winreg.OpenKey(winreg.HKEY_CURRENT_USER,KEY,0,winreg.KEY_SET_VALUE); winreg.SetValueEx(k,APP,0,winreg.REG_SZ,f'"{EXE}" --auto-start'); winreg.CloseKey(k)
def disable():
    try:
        k=winreg.OpenKey(winreg.HKEY_CURRENT_USER,KEY,0,winreg.KEY_SET_VALUE); winreg.DeleteValue(k,APP); winreg.CloseKey(k)
    except FileNotFoundError: pass
if __name__=='__main__': enable()

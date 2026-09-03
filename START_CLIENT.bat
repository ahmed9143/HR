@echo off
setlocal
cd /d "%~dp0"
set HR_MODE=auto
set HR_HOST=0.0.0.0
set HR_NO_BROWSER=0
python server.py

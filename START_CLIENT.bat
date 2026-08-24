@echo off
cd /d "%~dp0"
set HR_MODE=auto
set HR_NO_BROWSER=0
python server.py

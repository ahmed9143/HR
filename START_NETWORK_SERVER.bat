@echo off
cd /d "%~dp0"
set HR_MODE=network
set HR_HOST=0.0.0.0
set HR_NO_BROWSER=0
python server.py

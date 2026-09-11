@echo off
cd /d "%~dp0"
python -m PyInstaller --noconfirm --clean --onefile --windowed --name "HR Enterprise Tray" HR_TRAY.py

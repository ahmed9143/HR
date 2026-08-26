@echo off
setlocal EnableExtensions
cd /d "%~dp0"
where python >nul 2>&1 || (echo Python required.& exit /b 1)
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
python -m PyInstaller --noconfirm --clean --onefile --windowed --name "HR Enterprise" --collect-all reportlab --collect-all qrcode --add-data "fonts;fonts" server.py
if errorlevel 1 exit /b 1
if not exist "dist\HR Enterprise.exe" exit /b 1
echo READY: dist\HR Enterprise.exe
exit /b 0

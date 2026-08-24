@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo ================================================================
echo HR Enterprise 10.0 - COMPLETE WINDOWS BUILD
echo ================================================================
where python >nul 2>&1 || (echo Python required on BUILD PC only.& pause & exit /b 1)
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (echo Dependency install failed.& pause & exit /b 1)
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
python -m PyInstaller --noconfirm --clean --onefile --windowed --name "HR Enterprise" --hidden-import win32clipboard --hidden-import win32con --collect-all reportlab --add-data "fonts;fonts" server.py
if errorlevel 1 (echo EXE build failed.& pause & exit /b 1)
if exist dist\HR Enterprise.exe echo READY: dist\HR Enterprise.exe
pause

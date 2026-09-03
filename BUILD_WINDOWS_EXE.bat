@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo ================================================================
echo HR Enterprise 11.1.3 - WINDOWS BUILD
echo ================================================================
where python >nul 2>&1 || (echo Python required on BUILD PC only.& exit /b 1)
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (echo Dependency install failed.& exit /b 1)
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
python -m PyInstaller --noconfirm --clean --onefile --windowed --name "HR Enterprise" --icon "HR_Enterprise.ico" --hidden-import win32clipboard --hidden-import win32con --hidden-import qrcode --collect-all qrcode --collect-all reportlab --add-data "fonts;fonts" --add-data "assets;assets" server.py
if errorlevel 1 (echo EXE build failed.& exit /b 1)
if not exist "dist\HR Enterprise.exe" (echo EXE missing after build.& exit /b 1)
echo READY: dist\HR Enterprise.exe
exit /b 0

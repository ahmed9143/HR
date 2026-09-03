@echo off
setlocal EnableExtensions
cd /d "%~dp0"
where python >nul 2>&1 || (echo Python required on BUILD PC only.& exit /b 1)
python -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
if exist build\network rmdir /s /q build\network
python -m PyInstaller --noconfirm --clean --onefile --windowed --name "HR Enterprise Network Server" --icon "%CD%\HR_Enterprise.ico" --hidden-import win32clipboard --hidden-import win32con --hidden-import qrcode --collect-all qrcode --collect-all reportlab --add-data "%CD%\fonts;fonts" --add-data "%CD%\assets;assets" --add-data "%CD%\postgresql;postgresql" --distpath "dist\network" --workpath "build\network" --specpath "build\network" HR_NETWORK_SERVER.py
if errorlevel 1 exit /b 1
if not exist "dist\network\HR Enterprise Network Server.exe" exit /b 1
echo READY: dist\network\HR Enterprise Network Server.exe
exit /b 0

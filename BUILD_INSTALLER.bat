@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if not exist "dist\HR Enterprise.exe" call BUILD_WINDOWS_EXE.bat
if errorlevel 1 exit /b 1
if not exist "dist\network\HR Enterprise Network Server.exe" call BUILD_NETWORK_EXE.bat
if errorlevel 1 exit /b 1
where ISCC >nul 2>&1 || (echo Inno Setup compiler ISCC.exe is required on the BUILD PC.& exit /b 1)
if not exist installer mkdir installer
ISCC "HR_Enterprise.iss"
if errorlevel 1 (echo Installer build failed.& exit /b 1)
if not exist "installer\HR Enterprise Setup.exe" (echo Installer artifact missing.& exit /b 1)
echo READY: installer\HR Enterprise Setup.exe
exit /b 0

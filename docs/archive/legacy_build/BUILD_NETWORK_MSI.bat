@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if not exist "dist\network\HR Enterprise Network Server.exe" call BUILD_NETWORK_EXE.bat
if errorlevel 1 exit /b 1
where wix >nul 2>&1 || (echo WiX Toolset 'wix' is required on the BUILD PC.& exit /b 1)
if not exist installer mkdir installer
wix build "HR_Enterprise_Network.wxs" -o "installer\HR Enterprise Network Server.msi"
if errorlevel 1 exit /b 1
if not exist "installer\HR Enterprise Network Server.msi" exit /b 1
echo READY: installer\HR Enterprise Network Server.msi
exit /b 0

@echo off
setlocal EnableExtensions
cd /d "%~dp0"
call BUILD_WINDOWS_EXE.bat
if errorlevel 1 exit /b 1
call BUILD_NETWORK_EXE.bat
if errorlevel 1 exit /b 1
call BUILD_INSTALLER.bat
if errorlevel 1 exit /b 1
echo.
echo =========================================
echo HR Enterprise Windows build: SUCCESS
echo =========================================
echo Desktop EXE: dist\HR Enterprise.exe
echo Network EXE: dist\network\HR Enterprise Network Server.exe
echo Installer:    installer\
exit /b 0

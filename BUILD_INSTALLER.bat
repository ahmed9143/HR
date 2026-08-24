@echo off
setlocal EnableExtensions
cd /d "%~dp0"
where ISCC.exe >nul 2>&1
if errorlevel 1 (
  echo Inno Setup compiler ISCC.exe was not found.
  echo Install Inno Setup on the Windows build machine and run this again.
  exit /b 1
)
if not exist "dist\HR Enterprise.exe" (
  echo Build dist\HR Enterprise.exe first with BUILD_WINDOWS_EXE.bat
  exit /b 1
)
if exist installer rmdir /s /q installer
mkdir installer
ISCC.exe "HR_Enterprise.iss"
if errorlevel 1 exit /b 1
echo Installer build completed. Check installer folder.

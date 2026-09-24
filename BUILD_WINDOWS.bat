@echo off
REM ==========================================================================
REM HR Enterprise - local Windows build
REM
REM Does exactly what the GitHub Actions "build" job does, so a local build
REM and a CI build are the same artefact:
REM   1. install dependencies         4. smoke-test the packaged app
REM   2. run the full test suite      5. build the installer (if Inno Setup
REM   3. PyInstaller (onedir, spec)      is installed)
REM
REM Output:  dist\HR Enterprise\HR Enterprise.exe          (portable)
REM          installer\HR-Enterprise-Setup-<version>.exe   (installer)
REM
REM Replaces BUILD_ALL_WINDOWS / BUILD_INSTALLER / BUILD_NETWORK_EXE /
REM BUILD_NETWORK_MSI / BUILD_TRAY_EXE / BUILD_WINDOWS_EXE, which had drifted
REM apart (different flags, stale version 11.2.6, and an installer that
REM referenced an executable no script produced). Kept in docs\archive.
REM ==========================================================================
setlocal EnableExtensions
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PYTHONDONTWRITEBYTECODE=1

where python >nul 2>&1 || (echo [ERROR] Python 3.12 is required on the build PC only. & exit /b 1)
set /p VERSION=<VERSION.txt
echo ==========================================================
echo  HR Enterprise %VERSION% - Windows build
echo ==========================================================

echo [1/5] Installing dependencies...
python -m pip install --upgrade pip || exit /b 1
python -m pip install -r requirements.txt || (echo [ERROR] dependency install failed & exit /b 1)

if /i "%1"=="--skip-tests" goto build
echo [2/5] Running the test suite...
python RUN_ALL_TESTS.py || (echo [ERROR] tests failed - not building. Use --skip-tests to override. & exit /b 1)

:build
echo [3/5] Building with PyInstaller...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
python -m PyInstaller --noconfirm --clean HR_Enterprise.spec || (echo [ERROR] PyInstaller failed & exit /b 1)
if not exist "dist\HR Enterprise\HR Enterprise.exe" (echo [ERROR] executable missing after build & exit /b 1)

echo [4/5] Smoke-testing the packaged application...
python tests\packaging\TEST_FROZEN_APP.py "dist\HR Enterprise\HR Enterprise.exe" || (echo [ERROR] packaged app failed its smoke test & exit /b 1)

echo [5/5] Building installer...
set ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" (
  echo [SKIP] Inno Setup 6 not installed - portable build only.
  echo        Install from https://jrsoftware.org/isinfo.php to also build the installer.
  goto done
)
"%ISCC%" /DMyAppVersion=%VERSION% HR_Enterprise.iss || (echo [ERROR] installer build failed & exit /b 1)

:done
echo.
echo ==========================================================
echo  DONE
echo  Portable : dist\HR Enterprise\HR Enterprise.exe
if exist installer echo  Installer: installer\
echo ==========================================================
exit /b 0

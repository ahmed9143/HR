# -*- mode: python ; coding: utf-8 -*-
#
# HR Enterprise — PyInstaller build specification.
#
# Replaces the long command lines that were duplicated across six BUILD_*.bat
# files and had drifted apart. One spec, versioned with the code, used by both
# the local build script and GitHub Actions.
#
# Layout: ONEDIR, not onefile.
#   A onefile EXE unpacks itself into %TEMP% on every launch. On a hospital PC
#   with antivirus that is several seconds of disk scanning before the app even
#   starts — the same "it hangs when I open it" complaint the performance work
#   was fixing. Onedir starts immediately and is what the Inno Setup installer
#   packages anyway.
#
# Runtime data (database, keys, backups, logs) is NOT bundled: the app writes it
# to %PROGRAMDATA%\HR Enterprise\Data, so upgrades never touch user data.

import os
import sys
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# SPECPATH is the directory that contains this spec (not the spec file itself).
ROOT = os.path.abspath(SPECPATH)
IS_WINDOWS = sys.platform.startswith('win')

# Every application layer is imported by server.py at module level, so
# PyInstaller finds them on its own. They are listed explicitly anyway: the
# layer chain is load-order dependent, and a silently missing layer would ship
# an app with whole features — or security checks — absent.
APP_MODULES = [
    'v10_feature_pack', 'v11_completion', 'enterprise_completion', 'v12_enterprise',
    'production_ops', 'zkteco_core', 'zkteco_sync', 'zkteco_ui', 'zkteco_hospital',
    'zkteco_connector', 'zkteco_accdb_import', 'v13_security_ux', 'v14_final_hardening',
    'stable_final', 'pg_compat',
]

hiddenimports = list(APP_MODULES)
hiddenimports += collect_submodules('cryptography')
hiddenimports += collect_submodules('openpyxl')
hiddenimports += collect_submodules('reportlab')
hiddenimports += collect_submodules('qrcode')
hiddenimports += ['PIL', 'PIL.Image', 'PIL.ImageDraw', 'PIL.ImageFont']
try:
    hiddenimports += collect_submodules('zk')          # pyzk — ZKTeco devices
except Exception:
    pass
try:
    hiddenimports += collect_submodules('access_parser')
except Exception:
    pass
if IS_WINDOWS:
    hiddenimports += ['win32clipboard', 'win32con', 'win32api', 'pywintypes']

datas = [
    (os.path.join(ROOT, 'fonts'), 'fonts'),
    (os.path.join(ROOT, 'assets'), 'assets'),
    # production_ops falls back to this offline copy when qrcode is not
    # importable; in a frozen build __file__ resolves inside the bundle.
    (os.path.join(ROOT, 'vendor'), 'vendor'),
    (os.path.join(ROOT, 'VERSION.txt'), '.'),
    (os.path.join(ROOT, 'HR_Enterprise.ico'), '.'),
]
datas += collect_data_files('reportlab')
datas += collect_data_files('openpyxl')

# Nothing here is needed at runtime and some of it is large.
excludes = ['tkinter', 'matplotlib', 'numpy', 'pandas', 'scipy', 'IPython',
            'pytest', 'playwright', 'psycopg', 'psycopg2']

a = Analysis(
    [os.path.join(ROOT, 'server.py')],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='HR Enterprise',
    icon=os.path.join(ROOT, 'HR_Enterprise.ico'),
    console=False,              # windowed: no console window for end users
    disable_windowed_traceback=False,
    upx=False,                  # UPX-packed binaries trip antivirus heuristics
    version=os.path.join(ROOT, 'build', 'version_info.txt')
            if os.path.exists(os.path.join(ROOT, 'build', 'version_info.txt')) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='HR Enterprise',
)

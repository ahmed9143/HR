@echo off
python TEST_V10_COMPLETE.py
if errorlevel 1 exit /b 1
python TEST_V11_ACCEPTANCE.py
if errorlevel 1 exit /b 1
python -m py_compile server.py v10_feature_pack.py v9_patch.py v11_completion.py
echo ALL FEATURE TESTS PASS
pause

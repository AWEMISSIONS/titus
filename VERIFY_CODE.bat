@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Titus Code Verification

if not exist ".venv\Scripts\python.exe" (
  echo Run INSTALL_AND_RUN.bat first.
  pause
  exit /b 1
)

echo Checking Python source...
".venv\Scripts\python.exe" -m py_compile app\main.py app\ui.py app\engine.py app\vision.py app\database.py app\settings.py app\camera_diagnostics.py
if errorlevel 1 goto :fail

echo.
echo Core source passed the syntax check.
echo.
echo For camera troubleshooting, run DIAGNOSE_CAMERA.bat.
pause
exit /b 0

:fail
echo.
echo Titus verification failed. Keep this window open and take a screenshot.
pause
exit /b 1

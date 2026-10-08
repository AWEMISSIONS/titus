@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Titus Setup
color 0A

echo ============================================================
echo   TITUS - Local Vision Monitor - First-Time Setup
echo ============================================================
echo.

set "PYEXE="
where py >nul 2>nul && set "PYEXE=py -3.12"
if not defined PYEXE where python >nul 2>nul && set "PYEXE=python"

if not defined PYEXE (
  echo Python was not found. Titus will try to install Python 3.12.
  where winget >nul 2>nul
  if errorlevel 1 (
    echo Install Python 3.12 from python.org and run this file again.
    pause
    exit /b 1
  )
  winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
  if exist "%LocalAppData%\Programs\Python\Python312\python.exe" (
    set "PYEXE=%LocalAppData%\Programs\Python\Python312\python.exe"
  ) else (
    echo Python installed. Close this window and run INSTALL_AND_RUN.bat again.
    pause
    exit /b 0
  )
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating Titus environment...
  %PYEXE% -m venv .venv
  if errorlevel 1 goto :fail
)

".venv\Scripts\python.exe" -m pip install --upgrade pip wheel
if errorlevel 1 goto :fail

echo Installing Titus and local AI dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :fail

echo Preparing local AI model...
".venv\Scripts\python.exe" -c "from ultralytics import YOLO; YOLO('yolo26n.pt'); print('AI model ready.')"
if errorlevel 1 goto :fail

echo.
echo Titus is ready.
echo NEXT TIME use RUN_TITUS.bat.
start "Titus" ".venv\Scripts\pythonw.exe" app\main.py
pause
exit /b 0

:fail
echo.
echo Setup failed. This window will stay open.
pause
exit /b 1

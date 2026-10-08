@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run INSTALL_AND_RUN.bat first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" app\camera_diagnostics.py

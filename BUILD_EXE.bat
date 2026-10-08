@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run INSTALL_AND_RUN.bat first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install --upgrade pyinstaller
if errorlevel 1 goto :fail
rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul
set "MODELARG="
if exist "yolo26n.pt" set MODELARG=--add-data "yolo26n.pt;."
".venv\Scripts\pyinstaller.exe" --noconfirm --windowed --name Titus --collect-all ultralytics --collect-all torch --collect-all torchvision --collect-all customtkinter --collect-all pyttsx3 %MODELARG% app\main.py
if errorlevel 1 goto :fail
echo Finished. Open dist\Titus\Titus.exe
explorer "%CD%\dist\Titus"
pause
exit /b 0
:fail
echo Build failed.
pause
exit /b 1

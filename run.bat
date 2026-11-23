@echo off
rem Launch AI Gesture Jump (needs a webcam).
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found in PATH. Install Python 3.12 first.
  pause
  exit /b 1
)

python game\main.py
if errorlevel 1 (
  echo.
  echo [ERROR] Failed to start. Install dependencies first:
  echo     python -m pip install -r requirements.txt
  pause
  exit /b 1
)
endlocal

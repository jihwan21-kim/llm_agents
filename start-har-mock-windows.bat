@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="" (
  echo Usage: start-har-mock-windows.bat "recordings\site-id\run-folder"
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo Run setup-windows.bat first.
  exit /b 1
)
if not exist "%~1\bundle.json" (
  echo Recording bundle not found: %~1
  exit /b 1
)
echo Close any existing proxy on port 8080 before continuing.
.venv\Scripts\python.exe run_capture_proxy.py --recording "%~1"
if errorlevel 1 (
  echo Replay failed. Check the messages above.
  pause
  exit /b 1
)

@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run setup-windows.bat first.
  exit /b 1
)
if not exist "mailbox-recordings.json" (
  echo Missing mailbox-recordings.json
  exit /b 1
)
echo Close all existing proxies on port 8080 before starting.
echo Loading folders from mailbox-recordings.json
.venv\Scripts\python.exe run_capture_proxy.py --recordings-config mailbox-recordings.json
if errorlevel 1 (
  echo Mailbox replay failed. Check the messages above.
  pause
  exit /b 1
)

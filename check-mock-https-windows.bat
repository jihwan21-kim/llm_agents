@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Please run setup-windows.bat first.
  exit /b 1
)
echo Start your existing mock proxy in another PowerShell window first.
.venv\Scripts\python.exe diagnose-mock-https.py
exit /b %errorlevel%

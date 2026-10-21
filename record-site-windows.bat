@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run setup-windows.bat and setup-capture-windows.bat first.
  exit /b 1
)
.venv\Scripts\python.exe record_site.py %*

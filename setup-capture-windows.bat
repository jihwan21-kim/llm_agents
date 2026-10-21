@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo First run setup-windows.bat to install the proxy environment.
  exit /b 1
)
.venv\Scripts\python.exe -m pip install "playwright>=1.49,<2"
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m playwright install chromium
if errorlevel 1 exit /b 1
echo Capture dependencies installed.

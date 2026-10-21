@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="" (
  echo Usage: start-functional-gym-windows.bat js-demo
  echo        start-functional-gym-windows.bat study-board
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo Run setup-windows.bat first.
  exit /b 1
)
echo Close existing proxy on port 8080 and exit all experiment Chrome windows.
echo Starting site-specific functional JS with no upstream access.
.venv\Scripts\python.exe run_functional_gym.py --site "%~1"
if errorlevel 1 (
  echo Functional gym failed. Check messages above.
  pause
  exit /b 1
)

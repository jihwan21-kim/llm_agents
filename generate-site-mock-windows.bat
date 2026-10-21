@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="" (
  echo Usage: generate-site-mock-windows.bat js-demo
  echo        generate-site-mock-windows.bat study-board
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo Run setup-windows.bat first.
  exit /b 1
)
echo Generating approved offline Functional Mock for %~1...
.venv\Scripts\python.exe -m gym.build_approved_mock --site "%~1"
if errorlevel 1 (
  echo Generation failed. Only reviewed first-party sites are supported.
  exit /b 1
)
echo Starting verified generated mock. Close any existing proxy on port 8080.
call ".\start-functional-gym-windows.bat" "%~1" --generated

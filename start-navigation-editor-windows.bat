@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="" (
  echo Usage: start-navigation-editor-windows.bat "recording-folder"
  echo Select benign recorded buttons and save their destinations.
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
echo Close any previous mock proxy on port 8080 first.
echo Edit mode uses ONLY recorded snapshot screens and non-sensitive controls.
call "%~dp0start-har-mock-windows.bat" "%~1" --edit-navigation

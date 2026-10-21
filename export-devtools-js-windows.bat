@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="" (
  echo Usage: export-devtools-js-windows.bat "recording-folder"
  echo This exports archived original JS as local files for F12 ^> Sources ^> Workspace.
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
.venv\Scripts\python.exe export_recorded_js_for_devtools.py --recording "%~1"
if errorlevel 1 (
  echo Export failed. Confirm the recording has bundle.json and trace.har.
  exit /b 1
)

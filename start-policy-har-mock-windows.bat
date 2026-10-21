@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="" (
  echo Usage: start-policy-har-mock-windows.bat "recording-folder"
  echo The recorded origin must appear in gym\site_access_policy.json.
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
.venv\Scripts\python.exe -m gym.site_access_policy --recording "%~1" --mode static_replay
if errorlevel 1 (
  echo Site policy rejected this recording. No mock launched.
  exit /b 2
)
echo Launching sanitized snapshot mock with original JS available for reading.
echo Original third-party scripts will NOT execute.
call "%~dp0start-har-mock-windows.bat" "%~1" --agent-js-inspection

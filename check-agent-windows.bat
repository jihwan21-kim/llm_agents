@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv-agent\Scripts\python.exe" goto missing
.venv-agent\Scripts\python.exe experiments\ensure_proxy.py
if errorlevel 1 goto failed
.venv-agent\Scripts\python.exe experiments\runner.py check %*
if errorlevel 1 goto failed
pause
exit /b 0
:missing
echo Agent environment is missing. Run setup-agent-windows.bat first.
:failed
echo Check failed. See the message above.
pause
exit /b 1

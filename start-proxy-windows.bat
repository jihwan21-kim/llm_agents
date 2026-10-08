@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto missing
.venv\Scripts\python.exe run_proxy.py
if errorlevel 1 goto failed
exit /b 0
:missing
echo Proxy environment is missing. Run setup-windows.bat first.
pause
exit /b 1
:failed
echo Proxy stopped with an error. See the message above.
echo If dependencies are missing, run setup-windows.bat again.
pause
exit /b 1

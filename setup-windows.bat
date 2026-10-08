@echo off
cd /d "%~dp0"
py -3 -m venv .venv
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m pip install "mitmproxy==12.2.3"
if errorlevel 1 goto fail
echo Setup complete. Run start-proxy-windows.bat next.
pause
exit /b 0
:fail
echo Setup failed. Python 3.12 or newer and Internet access may be required.
pause
exit /b 1

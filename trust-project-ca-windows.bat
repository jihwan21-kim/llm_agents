@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0trust-project-ca-windows.ps1"
exit /b %errorlevel%

@echo off
cd /d "%~dp0"
.venv-agent\Scripts\python.exe experiments\runner.py run %*
pause

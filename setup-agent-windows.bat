@echo off
setlocal
cd /d "%~dp0"
py -3 -m venv .venv-agent
if errorlevel 1 goto failed
.venv-agent\Scripts\python.exe -m pip install -r experiments\requirements.txt
if errorlevel 1 goto failed
echo Agent setup complete. Uses installed Google Chrome.
echo Copy .env.example to .env and set OPENAI_API_KEY before a live run.
pause
exit /b 0
:failed
echo Agent setup failed.
pause
exit /b 1

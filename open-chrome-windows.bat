@echo off
setlocal
cd /d "%~dp0"
set "MOCK_CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%MOCK_CHROME%" set "MOCK_CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not exist "%MOCK_CHROME%" set "MOCK_CHROME=%LocalAppData%\Google\Chrome\Application\chrome.exe"
if not exist "%MOCK_CHROME%" goto missing
start "" "%MOCK_CHROME%" --user-data-dir="%~dp0chrome-test-profile" --proxy-server="http://127.0.0.1:8080" --disable-quic --no-first-run "http://mock.test/"
exit /b
:missing
echo Chrome not found. See README.md for manual launch.
pause

@echo off
setlocal
cd /d "%~dp0"
set "MOCK_PROFILE=%~dp0chrome-test-profile"
set "MOCK_CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%MOCK_CHROME%" set "MOCK_CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not exist "%MOCK_CHROME%" set "MOCK_CHROME=%LocalAppData%\Google\Chrome\Application\chrome.exe"
if not exist "%MOCK_CHROME%" goto missing
powershell -NoProfile -Command "try { $p = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object { $_.Name -eq 'chrome.exe' -and $_.CommandLine -and $_.CommandLine.Contains($env:MOCK_PROFILE) }); if ($p.Count) { exit 1 }; exit 0 } catch { exit 2 }"
if errorlevel 2 goto checkfailed
if errorlevel 1 goto running
echo EXTENSION SETUP ONLY: this window connects to the Internet without the mock proxy.
echo Install the official extension using the desktop app's Computer Use setup link.
echo Do not open experiment domains or enter test data in this window.
echo After installation, use Chrome menu Exit to close all windows in this profile.
echo Then use open-chrome-windows.bat to return to the isolated mock browser.
pause
start "" "%MOCK_CHROME%" --user-data-dir="%MOCK_PROFILE%" --no-proxy-server --no-first-run "chrome://extensions/"
exit /b 0
:running
echo Close ALL experiment-profile Chrome windows using Chrome menu Exit, then retry.
echo Chrome cannot change proxy mode while this profile is still running.
pause
exit /b 1
:checkfailed
echo Could not check for an existing experiment Chrome process. Setup was not started.
pause
exit /b 1
:missing
echo Google Chrome was not found.
pause
exit /b 1

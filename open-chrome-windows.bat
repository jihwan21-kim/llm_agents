@echo off
setlocal
cd /d "%~dp0"
set "MOCK_PROFILE=%~dp0chrome-test-profile"
set "MOCK_CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%MOCK_CHROME%" set "MOCK_CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not exist "%MOCK_CHROME%" set "MOCK_CHROME=%LocalAppData%\Google\Chrome\Application\chrome.exe"
if not exist "%MOCK_CHROME%" goto missing
powershell -NoProfile -Command "try { $p = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object { $_.Name -eq 'chrome.exe' -and $_.CommandLine -and $_.CommandLine.Contains($env:MOCK_PROFILE) }); if ($p.Count) { exit 1 }; exit 0 } catch { exit 2 }"
if errorlevel 1 goto running
start "" "%MOCK_CHROME%" --user-data-dir="%~dp0chrome-test-profile" --proxy-server="http://127.0.0.1:8080" --disable-quic --no-first-run "http://mock.test/"
exit /b
:missing
echo Chrome not found. See README.md for manual launch.
pause

:running
echo Close ALL experiment-profile Chrome windows using Chrome menu Exit and retry.
echo The proxy mode cannot be safely changed while this profile is running.
echo If no window is open, a background Chrome process or process-check error may remain.
pause
exit /b 1
